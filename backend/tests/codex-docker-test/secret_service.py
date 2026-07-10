"""Minimal D-Bus Secret Service for headless Docker.

Implements enough of org.freedesktop.Secret.Service to satisfy
the Rust `keyring` crate (v3.6.3) used by Codex CLI.
"""
import json
import os
import sys

from gi.repository import GLib, Gio

_ITEMS: dict[str, dict] = {}
_ITEM_CTR = 0
_SESSION = "/org/freedesktop/secrets/session/s0"
_COL_LOGIN = "/org/freedesktop/secrets/collection/login"
_COL_DEFAULT = "/org/freedesktop/secrets/aliases/default"

def _log(msg):
    print(f"[ss] {msg}", flush=True)

def _next_path():
    global _ITEM_CTR
    _ITEM_CTR += 1
    return f"{_COL_LOGIN}/{_ITEM_CTR}"

def _find(attrs: dict) -> list[str]:
    out = []
    for p, it in _ITEMS.items():
        ia = it.get("attributes", {})
        if all(ia.get(k) == v for k, v in attrs.items()):
            out.append(p)
    return out

def _secret_variant(secret_bytes: bytes):
    """Build a properly typed (oayays) GLib.Variant for a secret."""
    return GLib.Variant("(oayays)", (_SESSION, b"", secret_bytes, "text/plain"))

# ── Introspection XML ────────────────────────────────────────

SERVICE_XML = '''<node>
  <interface name="org.freedesktop.Secret.Service">
    <method name="OpenSession">
      <arg direction="in" type="s"/>
      <arg direction="in" type="v"/>
      <arg direction="out" type="v"/>
      <arg direction="out" type="o"/>
    </method>
    <method name="CreateCollection">
      <arg direction="in" type="a{sv}"/>
      <arg direction="in" type="s"/>
      <arg direction="out" type="o"/>
      <arg direction="out" type="o"/>
    </method>
    <method name="SearchItems">
      <arg direction="in" type="a{ss}"/>
      <arg direction="out" type="ao"/>
      <arg direction="out" type="ao"/>
    </method>
    <method name="GetSecrets">
      <arg direction="in" type="ao"/>
      <arg direction="in" type="o"/>
      <arg direction="out" type="a{o(oayays)}"/>
    </method>
    <property name="Collections" type="ao" access="read"/>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg direction="in" type="s"/>
      <arg direction="in" type="s"/>
      <arg direction="out" type="v"/>
    </method>
    <method name="GetAll">
      <arg direction="in" type="s"/>
      <arg direction="out" type="a{sv}"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect"><arg direction="out" type="s"/></method>
  </interface>
</node>'''

COLLECTION_XML = '''<node>
  <interface name="org.freedesktop.Secret.Collection">
    <method name="SearchItems">
      <arg direction="in" type="a{ss}"/>
      <arg direction="out" type="ao"/>
    </method>
    <method name="CreateItem">
      <arg direction="in" type="a{sv}"/>
      <arg direction="in" type="(oayays)"/>
      <arg direction="in" type="b"/>
      <arg direction="out" type="o"/>
      <arg direction="out" type="o"/>
    </method>
    <property name="Label" type="s" access="read"/>
    <property name="Locked" type="b" access="read"/>
    <property name="Items" type="ao" access="read"/>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg direction="in" type="s"/>
      <arg direction="in" type="s"/>
      <arg direction="out" type="v"/>
    </method>
    <method name="GetAll">
      <arg direction="in" type="s"/>
      <arg direction="out" type="a{sv}"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect"><arg direction="out" type="s"/></method>
  </interface>
</node>'''

ITEM_XML = '''<node>
  <interface name="org.freedesktop.Secret.Item">
    <method name="GetSecret">
      <arg direction="in" type="o"/>
      <arg direction="out" type="(oayays)"/>
    </method>
    <method name="Delete">
      <arg direction="out" type="o"/>
    </method>
    <property name="Label" type="s" access="readwrite"/>
    <property name="Attributes" type="a{ss}" access="readwrite"/>
    <property name="Locked" type="b" access="read"/>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg direction="in" type="s"/>
      <arg direction="in" type="s"/>
      <arg direction="out" type="v"/>
    </method>
    <method name="Set">
      <arg direction="in" type="s"/>
      <arg direction="in" type="s"/>
      <arg direction="in" type="v"/>
    </method>
    <method name="GetAll">
      <arg direction="in" type="s"/>
      <arg direction="out" type="a{sv}"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect"><arg direction="out" type="s"/></method>
  </interface>
</node>'''

SERVICE_NODE = Gio.DBusNodeInfo.new_for_xml(SERVICE_XML)
COLLECTION_NODE = Gio.DBusNodeInfo.new_for_xml(COLLECTION_XML)
ITEM_NODE = Gio.DBusNodeInfo.new_for_xml(ITEM_XML)

# ── Handlers ─────────────────────────────────────────────────

def handle_service(conn, sender, path, iface, method, params, inv):
    _log(f"Service.{iface}.{method}({path})")
    if iface == "org.freedesktop.DBus.Introspectable":
        inv.return_value(GLib.Variant("(s)", (SERVICE_XML,)))
    elif iface == "org.freedesktop.DBus.Properties":
        _, prop = params.unpack()
        if prop == "Collections":
            inv.return_value(GLib.Variant("(v)", (GLib.Variant("ao", [_COL_LOGIN]),)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownProperty", prop)
    elif iface == "org.freedesktop.Secret.Service":
        if method == "OpenSession":
            inv.return_value(GLib.Variant("(vo)", (GLib.Variant("s", ""), _SESSION)))
        elif method == "CreateCollection":
            inv.return_value(GLib.Variant("(oo)", (_COL_LOGIN, "/")))
        elif method == "SearchItems":
            attrs = dict(params[0])
            found = _find(attrs)
            _log(f"  SearchItems({attrs}) -> {found}")
            inv.return_value(GLib.Variant("(aoao)", (found, [])))
        elif method == "GetSecrets":
            item_paths = list(params[0])
            _log(f"  GetSecrets({item_paths})")
            secrets_dict = {}
            for p in item_paths:
                if p in _ITEMS:
                    secret = _ITEMS[p].get("secret", b"")
                    _log(f"    {p}: {len(secret)} bytes")
                    secrets_dict[p] = (_SESSION, b"", secret, "text/plain")
            inv.return_value(GLib.Variant("(a{o(oayays)})", (secrets_dict,)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
    else:
        inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", f"{iface}.{method}")


def handle_collection(conn, sender, path, iface, method, params, inv):
    _log(f"Collection.{iface}.{method}({path})")
    if iface == "org.freedesktop.DBus.Introspectable":
        inv.return_value(GLib.Variant("(s)", (COLLECTION_XML,)))
    elif iface == "org.freedesktop.DBus.Properties":
        pmethod = method
        if pmethod == "Get":
            _, prop = params.unpack()
            if prop == "Label":
                inv.return_value(GLib.Variant("(v)", (GLib.Variant("s", "Login"),)))
            elif prop == "Locked":
                inv.return_value(GLib.Variant("(v)", (GLib.Variant("b", False),)))
            elif prop == "Items":
                inv.return_value(GLib.Variant("(v)", (GLib.Variant("ao", list(_ITEMS.keys())),)))
            else:
                inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownProperty", prop)
        elif pmethod == "GetAll":
            iface_name = params.unpack()[0]
            props = {
                "Label": GLib.Variant("s", "Login"),
                "Locked": GLib.Variant("b", False),
                "Items": GLib.Variant("ao", list(_ITEMS.keys())),
            }
            inv.return_value(GLib.Variant("(a{sv})", (props,)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", pmethod)
    elif iface == "org.freedesktop.Secret.Collection":
        if method == "SearchItems":
            attrs = dict(params[0])
            found = _find(attrs)
            _log(f"  Col.SearchItems({attrs}) -> {found}")
            inv.return_value(GLib.Variant("(ao)", (found,)))
        elif method == "CreateItem":
            props_var = params[0]
            secret_tuple = params[1]
            replace = bool(params[2])

            label = ""
            attrs = {}
            for key in props_var.keys():
                val = props_var[key]
                if key == "org.freedesktop.Secret.Item.Label":
                    label = str(val)
                elif key == "org.freedesktop.Secret.Item.Attributes":
                    attrs = dict(val)

            secret_bytes = bytes(secret_tuple[2])

            existing = _find(attrs)
            if replace and existing:
                item_path = existing[0]
            else:
                item_path = _next_path()

            _ITEMS[item_path] = {"label": label, "attributes": attrs, "secret": secret_bytes}
            _log(f"  CreateItem: {item_path} label={label!r} secret={len(secret_bytes)}B")

            # Register item on D-Bus
            _register_item(conn, item_path)

            inv.return_value(GLib.Variant("(oo)", (item_path, "/")))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
    else:
        inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", f"{iface}.{method}")


def handle_item(conn, sender, path, iface, method, params, inv):
    _log(f"Item.{iface}.{method}({path})")
    item = _ITEMS.get(path, {})

    if iface == "org.freedesktop.DBus.Introspectable":
        inv.return_value(GLib.Variant("(s)", (ITEM_XML,)))
    elif iface == "org.freedesktop.DBus.Properties":
        if method == "Get":
            _, prop = params.unpack()
            if prop == "Label":
                inv.return_value(GLib.Variant("(v)", (GLib.Variant("s", item.get("label", "")),)))
            elif prop == "Attributes":
                inv.return_value(GLib.Variant("(v)", (GLib.Variant("a{ss}", item.get("attributes", {})),)))
            elif prop == "Locked":
                inv.return_value(GLib.Variant("(v)", (GLib.Variant("b", False),)))
            else:
                inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownProperty", prop)
        elif method == "Set":
            _, prop, val = params.unpack()
            if path in _ITEMS:
                if prop == "Attributes":
                    _ITEMS[path]["attributes"] = dict(val)
                elif prop == "Label":
                    _ITEMS[path]["label"] = str(val)
            inv.return_value(None)
        elif method == "GetAll":
            iface_name = params.unpack()[0]
            props = {
                "Label": GLib.Variant("s", item.get("label", "")),
                "Attributes": GLib.Variant("a{ss}", item.get("attributes", {})),
                "Locked": GLib.Variant("b", False),
            }
            inv.return_value(GLib.Variant("(a{sv})", (props,)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
    elif iface == "org.freedesktop.Secret.Item":
        if method == "GetSecret":
            secret = item.get("secret", b"")
            _log(f"  GetSecret -> {len(secret)} bytes")
            inv.return_value(GLib.Variant.new_tuple([_secret_variant(secret)]))
        elif method == "Delete":
            _ITEMS.pop(path, None)
            inv.return_value(GLib.Variant("(o)", ("/",)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
    else:
        inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", f"{iface}.{method}")


_registered_items: set[str] = set()

def _register_item(conn, path):
    if path in _registered_items:
        return
    for iface_info in ITEM_NODE.interfaces:
        try:
            conn.register_object(path, iface_info, handle_item)
        except Exception:
            pass
    _registered_items.add(path)


def handle_any(conn, sender, path, iface, method, params, inv):
    """Catch-all handler for any unregistered path — logs and tries to handle."""
    _log(f"CATCH-ALL: {iface}.{method}({path})")
    # Try to handle as item
    if path.startswith("/org/freedesktop/secrets/collection/"):
        parts = path.split("/")
        if len(parts) > 6:  # item path
            handle_item(conn, sender, path, iface, method, params, inv)
            return
        else:  # collection path
            handle_collection(conn, sender, path, iface, method, params, inv)
            return
    inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", f"Unhandled: {path} {iface}.{method}")


def on_bus(conn, name):
    for iface_info in SERVICE_NODE.interfaces:
        conn.register_object("/org/freedesktop/secrets", iface_info, handle_service)
    # Register collection at multiple possible paths
    for col_path in [_COL_LOGIN, _COL_DEFAULT,
                     "/org/freedesktop/secrets/collection/default",
                     "/org/freedesktop/secrets/collection/session"]:
        for iface_info in COLLECTION_NODE.interfaces:
            try:
                conn.register_object(col_path, iface_info, handle_collection)
            except Exception:
                pass  # may already be registered

    # Pre-register any existing items
    for path in list(_ITEMS.keys()):
        _register_item(conn, path)

    _log("Registered on D-Bus")


def on_name(conn, name):
    _log(f"Acquired: {name}")
    with open("/tmp/secret-service.ready", "w") as f:
        f.write(str(os.getpid()))


def on_lost(conn, name):
    _log(f"Lost: {name}")


if __name__ == "__main__":
    # Pre-populate from auth.json
    auth_path = os.path.expanduser("~/.codex/auth.json")
    if os.path.exists(auth_path):
        with open(auth_path) as f:
            auth = json.load(f)
        token = auth.get("tokens", {}).get("access_token", "")
        if token:
            path = _next_path()
            _ITEMS[path] = {
                "label": "Codex Auth",
                "attributes": {
                    "service": "Codex MCP Credentials",
                    "username": "codex-auth",
                    "application": "rust-keyring",
                    "target": "default",
                },
                "secret": token.encode(),
            }
            _log(f"Pre-populated: {len(token)} chars at {path}")

    Gio.bus_own_name(
        Gio.BusType.SESSION,
        "org.freedesktop.secrets",
        Gio.BusNameOwnerFlags.REPLACE,
        on_bus, on_name, on_lost,
    )
    _log("Starting...")
    GLib.MainLoop().run()

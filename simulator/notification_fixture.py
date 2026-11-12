"""Clearly synthetic display data; no API calls, credentials or personal text."""
FIXTURES = {
    "info": ("Service update", "Example node is healthy", "info", "server", "card"),
    "success": ("Backup complete", "Example backup verified", "success", "check", "badge"),
    "warning": ("Storage warning", "Example disk space is low", "warning", "warning", "toast"),
    "failure": ("Backup failed", "Example job needs attention", "failure", "error", "card"),
    "progress": ("Example backup", "Copying and verifying files", "info", "backup", "progress"),
}


def notification(kind, identity=None, progress=None):
    title, body, severity, icon, style = FIXTURES[kind]
    return {"id": identity or "demo-notification-" + kind, "title": title, "body": body,
            "type": severity, "priority": 3, "icon": icon, "style": style,
            "progress": (42 if progress is None else progress) if kind == "progress" else None,
            "ttl_seconds": 300, "age_seconds": 0}

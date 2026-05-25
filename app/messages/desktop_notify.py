

def send_notification(title: str, message: str, app_icon: str = "", app_name: str = "StreamCapEvo", timeout: int = 10):
    from plyer import notification
    notification.notify(
        title=title,
        message=message,
        app_icon=app_icon,
        app_name=app_name,
        timeout=timeout
    )


def should_push_notification(app) -> bool:
    # Flet-specific check: app.page is None in Qt version
    if getattr(app, "page", None):
        is_window_hidden = app.page.window.minimized or not app.page.window.visible
    else:
        # Qt version: assume we want notifications if enabled in config
        # We could check self.app.main_window.isMinimized() if needed, 
        # but for now, we'll keep it simple to avoid None errors.
        is_window_hidden = True 
        
    system_notification_enabled = app.settings.user_config.get("system_notification_enabled", True)
    
    # In Flet, app.page.web is used to avoid desktop notifications in browser
    is_web = getattr(app, "page", None) and getattr(app.page, "web", False)
    
    return not is_web and system_notification_enabled and is_window_hidden

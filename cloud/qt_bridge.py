"""Deliver the API client's connection and sign-in events to the Qt main thread.

The client can notice a dropped connection on the background sync thread; widgets may
only be touched on the main thread, so the events travel through queued Qt signals.
"""
from PyQt5.QtCore import QObject, pyqtSignal


class ConnectionEvents(QObject):
    connection_changed = pyqtSignal(bool)
    session_expired = pyqtSignal()

    def __init__(self, api, parent=None):
        super().__init__(parent)
        api.on_connection_change(self.connection_changed.emit)
        api.on_session_expired(self.session_expired.emit)


def open_database():
    """The database the app uses: the server, or the local file with OFFICE_BACKEND=local."""
    from cloud.config import api_url, use_local_database

    if use_local_database():
        from database.db_manager import DatabaseManager
        return DatabaseManager()
    from cloud.api import ApiClient
    from cloud.remote_db import RemoteDatabase
    return RemoteDatabase(ApiClient(api_url()))

"""Admin panel package.

Deliberately standalone: nothing in here imports a screen from ``ui`` except the
shared design tokens in ``ui.theme``, so the admin tool keeps working even while
the main application's UI is being changed.
"""

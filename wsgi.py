"""
wsgi.py — PythonAnywhere entry point.

In the PythonAnywhere web tab, set:
  Source code:    /home/<yourusername>/adi-workflow
  Working dir:    /home/<yourusername>/adi-workflow
  WSGI file:      /home/<yourusername>/adi-workflow/wsgi.py
"""
import sys
import os

# Add the project directory to Python path
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from app import create_app
application = create_app()

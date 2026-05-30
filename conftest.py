"""
pytest configuration — adds project root to sys.path
so 'backend' module is importable during tests.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

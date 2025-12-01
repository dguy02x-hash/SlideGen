#!/bin/bash
# Start script for Render deployment with custom Gunicorn config

# Use gunicorn with custom config for better timeout handling
gunicorn -c gunicorn_config.py server:app

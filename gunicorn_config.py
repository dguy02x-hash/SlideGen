# Gunicorn configuration for PresPilot
# Increases timeout for document processing and AI generation

# Timeout for workers (default is 30s, we need more for document processing)
timeout = 300  # 5 minutes for document uploads and AI processing

# Number of worker processes
workers = 2

# Worker class
worker_class = 'sync'

# Keep alive connections
keepalive = 5

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Bind address
bind = '0.0.0.0:5000'

import multiprocessing
import os

bind = "0.0.0.0:80"
backlog = 2048

workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
timeout = 180
keepalive = 10
preload_app = False

worker_tmp_dir = "/dev/shm"

accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

proc_name = "actionprowi-prod"

max_requests = 500  # Lower for async to ensure fresh event loops
max_requests_jitter = 50

graceful_timeout = 60

threads = 1

if os.getenv("APP_ENV") == "development":
    reload = True


def when_ready(server):
    server.log.info("Server is ready. Spawning workers")


def worker_init(worker):
    worker.log.info(f"Worker {worker.pid} initialized")


def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} exited")

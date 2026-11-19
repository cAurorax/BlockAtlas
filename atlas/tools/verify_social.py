"""End-to-end social test on a temporary database; never changes the live friendships."""
import os, subprocess, sys, tempfile, threading
import uvicorn
with tempfile.TemporaryDirectory() as folder:
    os.environ["ATLAS_DATA"]=folder
    from atlas.seed import app,seed
    seed()
    config=uvicorn.Config(app,host="127.0.0.1",port=0,log_level="error")
    with config.bind_socket() as sock:
        server=uvicorn.Server(config)
        thread=threading.Thread(target=server.run,kwargs={"sockets":[sock]})
        thread.start()
        try:
            subprocess.run(["node","atlas/tools/social.cjs"],env={**os.environ,"SOCIAL_TEST_URL":f"http://127.0.0.1:{sock.getsockname()[1]}"},check=True)
        finally:
            server.should_exit=True
            thread.join()

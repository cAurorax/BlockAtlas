"""Production entry point, contains no development paths."""
import os
from pathlib import Path
def main():
    storage=Path(os.environ["LOCALAPPDATA"])/"BlockAtlas"/"StudioRelease"/"data"
    os.environ["ATLAS_DATA"]=str(storage)
    os.environ["ATLAS_SERVICE_ONLY"]="1"
    from atlas.seed import app,seed
    import uvicorn
    @app.get("/release/ready",include_in_schema=False)
    def ready():return {"product":"BlockAtlasDesktop-v1"}
    seed()
    uvicorn.run(app,host="127.0.0.1",port=18283,loop="asyncio",http="h11",ws="none",lifespan="on",log_config=None,access_log=False)
if __name__=="__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()

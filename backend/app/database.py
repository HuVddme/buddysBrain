import os
from . import config  # noqa: F401
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_CLUSTER = os.getenv("MONGO_CLUSTER")
MONGO_DB = os.getenv("MONGO_DB")

MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_CLUSTER}/{MONGO_DB}?retryWrites=true&w=majority"

client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000,
                           connectTimeoutMS=5000, socketTimeoutMS=10000)
db = client[MONGO_DB]
collection = db["resources"]
usage_collection = db["usage_limits"]
passage_collection = db["resource_passages"]

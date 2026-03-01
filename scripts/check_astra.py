import os
from dotenv import load_dotenv
from astrapy import DataAPIClient

load_dotenv()

client = DataAPIClient(os.environ["ASTRA_DB_APPLICATION_TOKEN"])
db = client.get_database_by_api_endpoint(os.environ["ASTRA_DB_API_ENDPOINT"])
col = db.get_collection("ecommercedata", keyspace=os.environ["ASTRA_DB_KEYSPACE"])

doc = col.find_one({})
print("Sample doc:", doc)
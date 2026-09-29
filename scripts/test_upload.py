import io
from fastapi.testclient import TestClient
from fastapi import FastAPI
from skyguard.api.upload import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

csv_content = """station_id,ts_utc,T,RH,P
s1,2024-01-01T14:00:00Z,55.0,20.0,1005.0
s2,2024-01-01T14:00:00Z,25.0,50.0,1010.0
s3,2024-01-01T14:00:00Z,25.0,50.0,1010.0
"""

response = client.post(
    "/upload/score",
    files={"data_file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
)

print(response.json())

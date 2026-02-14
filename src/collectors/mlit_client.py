import os
import requests
from dotenv import load_dotenv

load_dotenv()

END_POINT = "https://data-platform.mlit.go.jp/api/v1/"
API_KEY = os.getenv("MLIT_API_KEY")


def post_query(query: str, query_name: str) -> list:
    """Post a GraphQL query to the MLIT Data Platform API."""
    response = requests.post(
        END_POINT,
        headers={"Content-type": "application/json", "apikey": API_KEY},
        json={"query": query},
    )
    response.raise_for_status()
    return response.json()["data"][query_name]
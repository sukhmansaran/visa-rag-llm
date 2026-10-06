from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Query(BaseModel):
    text: str

@app.get("/")
def read_root():
    return {"message": "Welcome to the Visa Chatbot API"}

from rag_agent import agent
from news_monitor import monitor

@app.post("/chat")
def chat(query: Query):
    response = agent.get_response(query.text)
    return {"response": response, "source": "ai_agent"}

@app.get("/news")
def get_news():
    news = monitor.fetch_latest_news()
    return {"news": news}


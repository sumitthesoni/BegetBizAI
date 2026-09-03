# BegetBiz Bot

BegetBiz Bot is a WhatsApp-powered AI sales assistant built with Python, FastAPI, LangChain, LangGraph, and the WhatsApp Business API. It listens for incoming WhatsApp messages, stores conversation memory, uses AI tools for image search and lead processing, and forwards qualified leads to an operations team.

The project is designed for lead qualification, visual discovery, and conversational bot workflows in a business context.

## Overview

The bot can:

- receive WhatsApp messages through a webhook
- detect spam, duplicates, and blocked users
- process user requests using a LangGraph-based AI agent
- call tools such as Google image search and lead forwarding
- store conversation memory in SQLite and sync summary data to Firestore
- send text, media, or summarized responses over WhatsApp

## Tech Stack

- Python 3.10+
- FastAPI
- Uvicorn
- LangChain
- LangGraph
- OpenAI GPT models
- Groq LLMs
- SQLite
- Firebase Firestore
- WhatsApp Cloud API
- Google Custom Search API

## Project Structure

```text
BegetBiz_BOT/
├── Agents/
│   ├── __init__.py
│   └── AGENT.py
├── Memory/
│   ├── __init__.py
│   └── sqldatabase.py
├── Prompts/
│   ├── summary_prompt.txt
│   └── system_prompt.txt
├── Whatsapp/
│   ├── receive_whatsapp.py
│   ├── send_whatsapp.py
│   └── utils/
│       ├── spamming.py
│       └── whatsapp_image_to_https.py
├── debugging/
│   ├── __init__.py
│   ├── exception.py
│   ├── logger.py
│   └── logshandler_class.py
├── utils/
│   ├── __init__.py
│   ├── analyze_image.py
│   ├── google_image_fetching_tool.py
│   └── lead_sender_tool.py
├── .env
├── config.py
├── main.py
├── requirements.txt
├── setup.py
├── README.md
├── begetbiz-e3f35-firebase-adminsdk-fbsvc-0a2e7951dd.json
└── .venv/ (optional local environment)
```

## Core Components

### 1. Webhook Server
The FastAPI application in `main.py` exposes the WhatsApp webhook endpoint and validates incoming events.

It handles:

- webhook verification for WhatsApp
- status update filtering
- duplicate message detection
- spam prevention
- blocked-user checks
- queue-based processing for each user

### 2. AI Agent Workflow
The agent in `Agents/AGENT.py` builds a LangGraph workflow that:

- loads thread memory for the current WhatsApp user
- sends the conversation context and system prompt to the LLM
- decides whether the response requires a tool call
- executes tools such as image fetching or lead sharing
- saves updated memory back to persistent storage

### 3. Conversation Memory
`Memory/sqldatabase.py` stores per-thread chat memory in SQLite and also syncs session summaries to Firestore.

This enables:

- persistent user context across chat messages
- summary-based memory retention
- thread-specific image tracking

### 4. Image Search and Analysis
`utils/google_image_fetching_tool.py` searches for relevant images using Google Custom Search and analyzes them using OpenAI.

This can support:

- product or reference image lookup
- visual matching for user requests
- contextual responses based on image content

### 5. Lead Forwarding
`utils/lead_sender_tool.py` and the WhatsApp sending utilities allow the assistant to send lead details and chat history to an operations contact.

### 6. WhatsApp Output Handling
`Whatsapp/receive_whatsapp.py` decides how responses should be sent back, including:

- plain text messages
- image messages with descriptions
- summary text delivery
- message retries and error fallback handling

## Environment Variables

Create a `.env` file in the project root with the following variables:

```env
GOOGLE_SEARCH_API_KEY=your_google_search_api_key
CSE_ID=your_custom_search_engine_id
Base_URL_for_Google_Custom_Search_API=https://www.googleapis.com/customsearch/v1

OPENAI_API_KEY=your_openai_api_key
GROQ_API_KEY=your_groq_api_key

LANGCHAIN_API_KEY=your_langchain_api_key
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=BegetBiz

IMGBB_API_KEY=your_imgbb_key
IMGBB_URL=https://api.imgbb.com/1/upload

WHATSAPP_API_URL=https://graph.facebook.com/v22.0
WHATSAPP_ACCESS_TOKEN=your_whatsapp_access_token
PHONE_NUMBER_ID=your_whatsapp_phone_number_id
```

Also ensure the Firebase credentials file exists in the project root:

```text
begetbiz-e3f35-firebase-adminsdk-fbsvc-0a2e7951dd.json
```

## Installation

1. Clone the repository:

```bash
git clone <your-repository-url>
cd BegetBiz_BOT
```

2. Create a virtual environment:

```bash
python -m venv .venv
```

3. Activate the environment:

On Windows:

```bash
.venv\Scripts\activate
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Configure your `.env` file and Firebase credentials.

## Running the Application

Start the server with:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

For development mode, you may use:

```bash
python main.py
```

If the project is run as a FastAPI service, the webhook endpoint will be available at:

```text
http://localhost:8000/webhook/
```

## WhatsApp Webhook Setup

Set the webhook URL in your WhatsApp Business configuration to a public endpoint such as:

```text
https://your-domain.com/webhook/
```

The app validates incoming requests using the `VERIFY_TOKEN` configured in `main.py`:

```python
VERIFY_TOKEN = "BegetBegetBiz*2"
```

> In production, it is better to store this in an environment variable instead of hardcoding it.

## Request Flow

1. A user sends a message on WhatsApp.
2. The server receives the webhook payload.
3. The message is validated for duplicates, blocking, and spam.
4. The message is queued per phone number.
5. The AI agent processes the message.
6. The agent may call tools like image lookup or lead forwarding.
7. A response is sent back to the user through WhatsApp.

## Features Summary

- AI-assisted WhatsApp conversations
- Tool-using LangGraph agent
- Google image search integration
- OpenAI-based image analysis
- Lead sharing to operations team
- Conversation memory and summarization
- Duplicate and spam filtering
- Firebase + SQLite persistence

## Troubleshooting

### App fails to start
Check:

- Python version compatibility
- missing dependency installation
- invalid `.env` keys
- Firebase credential file path

### WhatsApp webhook verification fails
Check:

- public access to the webhook server
- correct `hub.verify_token` value
- validation callback parameters from WhatsApp

### Messages are not processed
Check:

- valid WhatsApp access token
- correct phone number configuration
- endpoint reachability
- database permissions and logs

### LLM or API tools fail
Check:

- valid API keys in `.env`
- account quotas and billing status
- network connectivity
- response format expectations from external APIs

## Deployment Recommendations

For production deployment, use a service such as:

- Railway
- Render
- Heroku
- DigitalOcean App Platform
- Docker + VPS

Recommended production safeguards:

- keep secrets in environment variables
- use HTTPS for incoming webhooks
- rotate API keys regularly
- monitor logs and exception tracking
- secure Firebase credentials properly

## License

This project is intended for internal or project-specific use. Add your preferred license here if you plan to distribute it publicly.

## Notes

This project is a business automation assistant focused on lead qualification and visual discovery. It is not a generic starter chatbot template and is tailored for real-world WhatsApp-based sales workflows.

This project is currently distributed without an explicit license file. Please confirm the licensing terms before using it in production or redistributing it.

## Maintainer

This project is primarily configured for BegetBiz operations and WhatsApp lead handling workflows. If you are extending it, keep the environment configuration, token handling, and Firebase setup synchronized with the deployment environment.

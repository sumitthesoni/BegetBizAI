# ––– Standard Library Imports –––
import os
import sys
import random

# ––– Third-Party/External Library Imports –––
import requests
import openai
import certifi
from dotenv import load_dotenv

# ––– Langchain/Groq Related Imports –––
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from typing import List

# ––– Local Application Imports –––
from debugging.exception import customException

# Load environment variables from .env file
load_dotenv()

# Load Google search credentials
api_key = os.getenv('GOOGLE_SEARCH_API_KEY')
cse_id = os.getenv('CSE_ID')
GROQ_API_KEY=os.getenv('GROQ_API_KEY')

# Initalize llm
llm=ChatGroq(model='llama-3.1-8b-instant', temperature=1)

# Setting openai key
openai.api_key=os.getenv('OPENAI_API_KEY')

@tool
def fetch_google_images(query: str) -> List[str]:
    """
    This is the 'fetch_google_images' tool, designed to retrieve and analyze images 
    based on a user-provided query topic. It is tightly scoped for use in specific, 
    visual exploration tasks.

    🔍 What it does:
    - Searches Google for top relevant images matching the query.
    - Analyzes each image using the OPENAI API to extract detailed visible content (up to 800 tokens).
    - Returns image summary

    Parameters:
    ----------
    query : str
        The search term or topic to fetch and analyze images for.

    Returns:
    -------
    List[str] - A detailed GPT-generated summary of the image's visual content with link List[link,summary].
    """
    clean_query=llm.invoke(f'''
    Use the user's full description to understand the context, then convert it into a concise and effective Google search term that captures the visual essence — for example, if the user says something like:

        USER: "Show me an image of a dog with a cat where the dog is wearing a hat but the cat is not"
        AI: dog wearing hat with cat beside it

    - This keeps it natural, instructional, and clear for the model to follow.

    ⚠️ Just provide the search term — nothing else.

    Description: {query}
    ''')
    try:
        # Base URL for Google Custom Search API
        url = os.getenv('Base_URL_for_Google_Custom_Search_API')
        
        # Exclude social media platforms in search results
        excluded_sites = '-site:instagram.com -site:facebook.com -site:twitter.com'
        modified_query = f"{clean_query.content} {excluded_sites}"

        # Request 10 image candidates
        params = {
            'q': modified_query,
            'cx': cse_id,
            'key': api_key,
            'num': 10,                    # get ten candidates
            'searchType': 'image',
            'fileType': 'jpg,png',        # restrict to jpg or png
            'imgType': 'photo',           # only real photos
            'safe': 'medium'
        }
        response = requests.get(url, params=params, verify=certifi.where())
        response.raise_for_status()
        data = response.json()

        # Filter out any proxy or invalid URLs
        candidates = []
        for item in data.get('items', []):
            link = item['link']
            if link.startswith('https://') and 'next/image' not in link:
                candidates.append(link)

        if not candidates:
            return 'No images retrieved, Attempt to retrieve the image using another but accurate search phrase.'
        
        # Shuffling candidates
        random.shuffle(candidates)
        
        # Attempt each candidate until one succeeds
        for url_candidate in candidates:
            try:
                analysis = openai.chat.completions.create(
                    model='gpt-4o',
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that describes and analyzes images."},
                        {"role": "user", "content": [
                            {"type": "text", "text": "Describe this image in detail and infer what it's about."},
                            {"type": "image_url", "image_url": {"url": url_candidate}},
                        ]}
                    ],
                    max_tokens=800,
                    temperature=0.5
                )
                summary = analysis.choices[0].message.content
                if summary:
                    return [url_candidate, summary]
            except openai.BadRequestError:
                # Skip invalid URL and try next
                continue

        # If loop ends without success
        return "All image URLs failed analysis. Please try another query or inform the user that the image cannot be fetched due to a technical issue."

    except Exception as e:
        # Wrap any unexpected errors
        raise customException(e, sys)
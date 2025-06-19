import os
import openai

# Setting openai key
openai.api_key=os.getenv('OPENAI_API_KEY')

async def analyze_image(url: str) -> str:
    """
    This is the 'analyze_image' function, used strictly to analyze an image from a URL 
    provided directly by the user.

    ✅ Usage Conditions:
    - Only use this tool when the user explicitly provides a valid image URL.
    - The URL must start with "https://"  or "http://" — do not invoke this tool for any other input.

    ⚠️ Do NOT use this tool for any other scenarios.
    """
    # 1) Basic validation (no regex)
    if not (url.startswith("http://") or url.startswith("https://")):
        return "URL is invalid"
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that describes and analyzes images."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Describe this image in detail and infer what it's about."},
                    {"type": "image_url", "image_url": {"url": url}},
                ]}
            ],
            max_tokens=800,
            temperature=0.7
        )

        # Append (image_url, summary) to the list
        result=response.choices[0].message.content
    except Exception as e:
        # If the model call itself fails, return a friendly error string
        return "URL is invalid or Failed to analyze image: " + str(e)
    return result.strip()
import os  # For accessing environment variables
import re  # For regex operations
import sys  # For system-specific parameters and functions
import uuid # For generating random id
import warnings # For ignoring the warnings
import string # For getting list of punctuations
warnings.filterwarnings("ignore")


from pydantic import BaseModel, Field  # For defining structured schemas
from typing import List  # Type hinting for lists
from langchain_core.output_parsers import PydanticOutputParser  # To parse LLM output into Pydantic models
from langchain_core.prompts import PromptTemplate  # For building prompt templates
from langchain_core.messages import HumanMessage  # Represents user messages
from langchain_openai import ChatOpenAI  # OpenAI chat model interface

from Agents.AGENT import AGENT  # Custom agent workflow
from Whatsapp.send_whatsapp import send_image_by_id, upload_media, send_text_message  # WhatsApp API helpers
from Whatsapp.utils.whatsapp_image_to_https import whatsapp_image_to_https  # Converts WhatsApp media to public URLs
from Memory.sqldatabase import get_image_store, update_image_store  # Persistent storage for images
from utils.analyze_image import analyze_image  # Image analysis utility

from debugging.logger import logging  # Custom logger
from debugging.exception import customException  # Exception wrapper

# Langsmith for tracing
from langsmith import traceable
from langsmith.run_trees import RunTree

# Langchain tracing setup
LANGCHAIN_TRACING_V2=os.getenv('LANGCHAIN_TRACING_V2')
LANGCHAIN_API_KEY=os.getenv('LANGCHAIN_API_KEY')
LANGCHAIN_PROJECT=os.getenv('LANGCHAIN_PROJECT')

# Load environment variables for tokens
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Initialize the GPT-based language model
llm = ChatOpenAI(model='gpt-4o-mini')  # Using the mini model for fast responses

# Initialize the custom agent for handling messages
app = AGENT()

# ====================
# Utility Functions
# ====================

async def extract_url(text):
    if text is None:
        return None
    m = re.findall(r"https?://\S+", text)
    links=[link.rstrip(string.punctuation) for link in m]
    return links if links else None


async def llm_sending_image_with_description(response: str) -> dict:
    # Define the Pydantic schema with clearer field descriptions
    class pydanticobject(BaseModel):
        links: List[str] = Field(description='Ordered list of ALL unique links from the message. Empty list ONLY for final confirmation format')
        description: List[str] = Field(description='Clean descriptions in exact same order as links. NO URLs allowed. For final confirmation, single-item list with full content')

    parser = PydanticOutputParser(pydantic_object=pydanticobject)

    # Enhanced prompt with explicit ordering rules
    prompt_template = (
        "Your task: Extract links and descriptions from messages with strict rules.\n\n"
        "PROCESSING RULES:\n"
        "- Extract ALL unique links in ORDER of appearance\n"
        "- For EACH link, extract its CLEAN description:\n"
        "* Remove ALL URLs from descriptions\n"
        "* Maintain ORIGINAL text order (1st link → 1st description)\n"
        "* PRESERVE formatting (bullet points, paragraphs)\n"
        "* COMBINE multi-part descriptions for same link\n\n"
        "SPECIAL CASE: If no links found\n"
        "- Return empty list for 'links'\n"
        "- Return empty list for 'description'\n\n"
        "EXAMPLES:\n"
        "[Regular Input]: 'Check [design1](url1)... Description: Modern layout... See [demo](url2)... Features: Clean typography'\n"
        "[Output]: {{'links': ['url1','url2'], 'description': ['Modern layout', 'Features: Clean typography']}}\n\n"
        "----------------------\n"
        "ACTUAL INPUT:\n{input}\n\n"
        "STRICT OUTPUT FORMAT:\n{format_instructions}"
    )
    
    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["input"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )

    chain = prompt | llm | parser
    result = chain.invoke({'input': response})
    
    return dict(result)

# ====================
# Output Handling
# ====================

async def output_handler(output, phone_number):
    # Extract the last message content from the LLM output
    last_content = output["messages"][-1].content

    # Extract URLs from the last content using the extract_url function
    urls = await extract_url(last_content)
        
    # Check if any URLs were found in the message
    if urls:
        required_keywords = ["name", "company", "service","deadline"]
        last_content_lower = last_content.lower()
        
        # Checking if last content holds summary or not
        if all(word in last_content_lower for word in required_keywords):
            logging.info("LLM sent Summary")
            await send_text_message(to=phone_number, message=last_content)
            return None
        
        logging.info("LLM sent image or other links")
        try:
            # Retrieve stored images/messages for this phone number to avoid duplicates
            image_store = await get_image_store(thread_id=phone_number)

            for not_image_link in urls:
                # Get the media_id by reverse lookup using the link
                # Retrieve previously stored image_id
                matched_list_of_links = [k for k, v in image_store.items() if v == not_image_link]

                for r_id in matched_list_of_links:
                    if len(r_id)==36:
                        logging.info("LLM sent reel or other link")
                        await send_text_message(to=phone_number, message=last_content)
                        return None

            # Use LLM to associate image links with descriptions
            link_desc = await llm_sending_image_with_description(response=last_content)
            links = link_desc['links']
            descriptions = link_desc['description']
                    
            # Loop through each image link and its associated description
            for link, desc in zip(links, descriptions):
                # Process only if this image wasn't already sent
                if link not in list(image_store.values()):
                    logging.info("image not in image store")

                    try:
                        # Upload image to WhatsApp and retrieve media_id
                        media_id = await upload_media(image_url=link)
                    except Exception as e:
                        logging.error(f"Upload failed: {e}")
                        await send_text_message(to=phone_number, message=last_content)
                        continue

                    # Send the uploaded image to user via WhatsApp
                    ret_img, response_img = await send_image_by_id(to=phone_number, media_id=media_id)

                    # If image was sent successfully
                    if ret_img:
                        # Extract the WhatsApp image message ID
                        image_id = response_img.get("messages", [{}])[0].get("id")

                        # Store both media_id → link and link → image_id in the image store
                        image_store[media_id] = link
                        image_store[image_id] = link

                        # Save updated image store to persistent storage
                        await update_image_store(thread_id=phone_number, image_store_data=image_store)

                        # Send the image's associated description text to the user
                        ret_msg, response_msg = await send_text_message(to=phone_number, message=desc)

                        # If description was sent successfully
                        if ret_msg:
                            # Extract WhatsApp message ID for the description
                            msg_id = response_msg.get("messages", [{}])[0].get("id")

                            # Store description → message_id in the image store
                            image_store[msg_id] = desc

                            # Save updated store
                            await update_image_store(thread_id=phone_number, image_store_data=image_store)

                        # If sending description failed
                        else:
                            logging.info('Error occurred during sending message')
                            await send_text_message(to=phone_number, message="Sorry for inconvenience but I cannot send description of provided image")

                    # If sending image failed
                    else:
                        logging.info('Cannot send Image and description due to error')
                        await send_text_message(to=phone_number, message="Sorry for inconvenience but I cannot send image and description")

                # If the image was already sent previously
                else:
                    logging.info("image already in image store")

                    # Retrieve previously stored image_id
                    matched_list_of_links = [k for k, v in image_store.items() if v == link]

                    media_id=None
                    for m_id in matched_list_of_links:
                        if len(m_id)==16:
                            media_id=m_id
                            break
                        else:
                            media_id=m_id

                    ret_img = False
                    response_img = None

                    if media_id:
                        # Resend the image using stored media_id
                        ret_img, response_img = await send_image_by_id(to=phone_number, media_id=media_id)

                    # If image sent successfully
                    if ret_img:
                        # Send the corresponding description again
                        ret_msg, response_msg = await send_text_message(to=phone_number, message=desc)

                        if ret_msg:
                            msg_id = response_msg.get("messages", [{}])[0].get("id")
                            image_store[msg_id] = desc
                            await update_image_store(thread_id=phone_number, image_store_data=image_store)
                        else:
                            logging.info('Error occurred during sending message')
                            await send_text_message(to=phone_number, message="Sorry for inconvenience but I cannot send description of provided image")

                    else:
                        logging.info('Cannot send Image and description due to error')
                        await send_text_message(to=phone_number, message="Sorry for inconvenience but I cannot send image and description")              

        except Exception as e:
            logging.warning(f"Error occurred during sending image with description error : {e}")
            await send_text_message(to=phone_number, message='Sorry for inconvenience but I cannot reply right now.')
            

    # If no image URLs were found, just send the plain text
    else:
        try:
            # Retrieve stored images/messages for this phone number to avoid duplicates
            image_store = await get_image_store(thread_id=phone_number)
            # Send the message text as-is
            ret_msg, response_msg = await send_text_message(to=phone_number, message=last_content)

            # If message sent successfully
            if ret_msg:
                msg_id = response_msg.get("messages", [{}])[0].get("id")
                image_store[msg_id] = last_content
                await update_image_store(thread_id=phone_number, image_store_data=image_store)

            else:
                logging.info('Error occurred during sending message')
                await send_text_message(to=phone_number, message="Sorry for inconvenience but I cannot send message right now")

        except Exception as e:
            logging.warning(f"Error occurred during sending message error : {e}")
            await send_text_message(to=phone_number, message='Sorry for inconvenience but I cannot send message right now')    

# ====================
# Main Webhook Handler
# ====================
@traceable(name="incoming_whatsapp_message")
async def handle_whatsapp_message(data: dict):
    try:
        logging.info("Processing incoming WhatsApp message")

        # ───────────────────────────────────────────────────────────────
        # Extract the WhatsApp message data from the webhook payload
        # ───────────────────────────────────────────────────────────────
        value = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})

        message_data = value
        message = message_data["messages"][0]
        message_type = message.get("type")
        phone_number = message.get("from")
        context = message.get('context')

        # ───────────────────────────────────────────────────────────────
        # Case 1: Incoming Text Message Without Any Context
        # ───────────────────────────────────────────────────────────────
        if message_type == "text" and not context:
            user_text = message["text"]["body"]
            logging.info(f"Received text from {phone_number}: {user_text}")
            
            # Save the incoming user message to store
            image_store = await get_image_store(thread_id=phone_number)
            image_store[message['id']] = user_text+'.'
            logging.info(f"new message context id : {message['id']}")
            await update_image_store(thread_id=phone_number, image_store_data=image_store)            

            # Check and store any URLs present in the message
            urls = await extract_url(user_text)
            if urls:
                for link in urls:
                    if link not in list(image_store.values()):
                        logging.info("New reel link indentified")
                        random__id = str(uuid.uuid4())
                        image_store = await get_image_store(thread_id=phone_number)
                        image_store[random__id] = link
                        await update_image_store(thread_id=phone_number, image_store_data=image_store)

            # Call LLM with plain user text input
            output = app.invoke(
                {"messages": [user_text]},
                config={"configurable": {"thread_id": phone_number}}
            )
            await output_handler(output, phone_number)

            # LangSmith run tracing
            run = RunTree(name="Incoming WhatsApp", inputs={"from": phone_number, "message": message["text"]["body"]})
            run.post()

        # ───────────────────────────────────────────────────────────────
        # Case 2: Text Message With Context (Replies to Image or Message)
        # ───────────────────────────────────────────────────────────────
        elif message_type == "text" and context:
            user_text = message["text"]["body"]
            context_id = context.get('id')
            logging.info(f"Received text with context from {phone_number}: '{user_text}', context_id={context_id}")

            # Try to find the image URL or referenced message using context ID
            image_url_store = await get_image_store(thread_id=phone_number)
            image_url = image_url_store.get(context_id)

            # Store new reel link if present in message
            urls = await extract_url(user_text)
            if urls:
                for link in urls:
                    if link not in list(image_store.values()):
                        logging.info("New reel link indentified")
                        random__id = str(uuid.uuid4())
                        image_store[random__id] = link
                        await update_image_store(thread_id=phone_number, image_store_data=image_store)

            # Checking if value is key is link or message
            link_or_message=await extract_url(image_url)

            if not link_or_message:
                # Case where context is message not image
                logging.info(f"User send new message with previous message")
                sender_number = context.get('from')

                # Importing image store
                image_url_store = await get_image_store(thread_id=phone_number)

                if sender_number == phone_number:
                    # Message is in reply to a previous human message
                    logging.info(f'User send message with Previous human message: {user_text}')
                    previous_human_message = image_url_store.get(context_id)
                    logging.info(f'Previous human message: {previous_human_message}')

                    user_msg = HumanMessage(
                        content = (
                            f"Based on my previous message, please respond to my new request:\n"
                            f"Previously I said: {previous_human_message}\n"
                            f"My new request: {user_text}"
                        )
                    )

                    output = app.invoke(
                        {"messages": [user_msg]},
                        config={"configurable": {"thread_id": phone_number}}
                    )
                    await output_handler(output=output, phone_number=phone_number)

                elif sender_number != phone_number:
                    # Message is in reply to an AI-generated message
                    logging.info(f'User send message with AI message: {user_text}')
                    previous_ai_message = image_url_store.get(context_id)
                    logging.info(f'Previous AI message: {previous_ai_message}')

                    user_msg = HumanMessage(
                    content = (
                        f"Based on your previous message, please respond to my new request:\n"
                        f"Previously you said: {previous_ai_message}\n"
                        f"My new request: {user_text}"
                    )
                )
                    
                    output = app.invoke(
                        {"messages": [user_msg]},
                        config={"configurable": {"thread_id": phone_number}}
                    )
                    await output_handler(output=output, phone_number=phone_number)                    

            else:
                # If image context found, include image URL in message
                user_msg = HumanMessage(
                    content=(
                        f"Image Link: {image_url}\n"
                        f"query: {user_text}"
                    )
                )
                output = app.invoke(
                    {"messages": [user_msg]},
                    config={"configurable": {"thread_id": phone_number}}
                )
                await output_handler(output=output, phone_number=phone_number)

                # LangSmith run tracing
                run = RunTree(name="Incoming WhatsApp", inputs={"from": phone_number, "message": message["text"]["body"]})
                run.post()

        # ───────────────────────────────────────────────────────────────
        # Case 3: Incoming Image Message
        # ───────────────────────────────────────────────────────────────
        elif message_type == "image":
            image_info = message["image"]
            media_id = image_info["id"]
            image_id = message["id"]
            caption = image_info.get("caption")
            logging.info(f"Received image from {phone_number} with caption: {caption}")

            # Send acknowledgment to user
            await send_text_message(to=phone_number, message="Thanks for the image! I'm analyzing it now. Please give me a moment...")

            if caption:
                # Handle captioned image
                image_store = await get_image_store(thread_id=phone_number)
                if image_id not in list(image_store.keys()):
                    image_url = whatsapp_image_to_https(media_id=media_id)
                    desc = await analyze_image(url=image_url)

                    user_msg = HumanMessage(
                        content=(
                            "Please reference this image description below:\n"
                            f"<image_description>\n{desc}\n</image_description>\n"
                            f"Image Link: {image_url}\n"
                            f"My Request: {caption}\n"
                            f"Note: Dont share **same** link in response of my request"
                        )
                    )
                    output = app.invoke(
                        {"messages": [user_msg]},
                        config={"configurable": {"thread_id": phone_number}}
                    )
                    await output_handler(output=output, phone_number=phone_number)

                    image_store[media_id]=image_url
                    image_store[image_id] = image_url
                    await update_image_store(thread_id=phone_number, image_store_data=image_store)
                else:
                    # Reuse existing image URL
                    logging.info(f"Image {image_id} already processed for {phone_number}")
                    image_url = image_store.get(image_id)

                    user_msg = HumanMessage(
                        content=(
                            f"Image Link: {image_url}\n"
                            f"query: {caption}"
                        )
                    )
                    output = app.invoke(
                        {"messages": [user_msg]},
                        config={"configurable": {"thread_id": phone_number}}
                    )
                    await output_handler(output=output, phone_number=phone_number)

            else:
                # Handle image without caption: respond with analysis and wait for user's query
                logging.info(f"New Image {image_id} send by {phone_number}")
                logging.info(f"media_id: {media_id}")

                try:
                    image_url = whatsapp_image_to_https(media_id=media_id)
                except:
                    await send_text_message(to=phone_number,message="Sorry, I couldn't process the image due to a technical issue. Could you please try again later? Meanwhile, could you please explain your visual requirements in text?")
                    return ''

                desc = await analyze_image(url=image_url)

                user_msg = HumanMessage(
                    content=(
                        "Please reference this image description below:\n"
                        f"<image_description>\n{desc}\n</image_description>\n"
                        f"Image Link: {image_url}\n"
                        f"Based on the description, identify the topic of the image as well.\n"
                        f"and wait for my query\n"
                        f"Just say : `I've analyzed the image of [**Topic**]`"
                        "\n(**Dont't** share link or description with me)"
                    )
                )
                output = app.invoke(
                    {"messages": [user_msg]},
                    config={"configurable": {"thread_id": phone_number}}
                )
                await output_handler(output=output, phone_number=phone_number)

                image_store = await get_image_store(thread_id=phone_number)
                image_store[image_id] = image_url
                image_store[media_id] = image_url
                await update_image_store(thread_id=phone_number, image_store_data=image_store)

        # ───────────────────────────────────────────────────────────────
        # Case 4: Unsupported Message Type
        # ───────────────────────────────────────────────────────────────
        elif message_type == "unsupported":
            pass

        # ───────────────────────────────────────────────────────────────
        # Case 5: Any Other Unknown Message Type
        # ───────────────────────────────────────────────────────────────
        else:
            logging.warning(f"Unsupported message type from {phone_number}")
            await send_text_message(to=phone_number, message='Invalid Request!')

    # ───────────────────────────────────────────────────────────────
    # Global Exception Handling
    # ───────────────────────────────────────────────────────────────
    except Exception as e:
        logging.exception(str(customException(e, sys)))
        await send_text_message(to=phone_number, message='server busy')
        return {"error": str(e)}

from pyexpat.errors import messages
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import ChatSession, ChatMessage, UploadedFile
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth import logout
import requests
import os
import traceback
import google.generativeai as genai
from django.conf import settings
from dotenv import load_dotenv
from django.contrib import messages as django_messages
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from pathlib import Path
import mimetypes

load_dotenv()

def handler404(request, exception):
    return render(request, '404.html', status=404)

def handler500(request):
    return render(request, '500.html', status=500)
def chat_sessions(request):
    sessions = ChatSession.objects.filter(user=request.user)
    return render(request, 'chat/sessions.html', {'sessions': sessions})

@login_required
def index(request):
    if request.user.is_authenticated:
        sessions = ChatSession.objects.filter(user=request.user)
    else:
        sessions = []
    return render(request, 'chatbot/index.html', {'sessions': sessions})

@login_required
def chat(request, session_id=None):
    if session_id:
        try:
            chat_session = ChatSession.objects.get(id=session_id, user=request.user)
            messages = ChatMessage.objects.filter(session=chat_session).order_by('created_at')
        except ChatSession.DoesNotExist:
            return redirect('index')
    else:
        # Create a new session if none exists
        chat_session = ChatSession.objects.create(
            user=request.user,
            title="New Chat"
        )
        messages = []
    
    return render(request, 'chatbot/chat.html', {
        'session': chat_session,
        'messages': messages,
    })

@login_required
def new_chat(request):
    if request.method == 'POST':
        title = request.POST.get('title', 'New Chat')
        chat_session = ChatSession.objects.create(user=request.user, title=title)
        return redirect('chat', session_id=chat_session.id)
    return redirect('index')

def is_image_file(file):
    # Check if the file is an image based on MIME type
    mime_type = mimetypes.guess_type(file.name)[0]
    return mime_type and mime_type.startswith('image/')

@login_required
def send_message(request):
    if request.method == 'POST':
        try:
            # Verify API key is valid
            if not hasattr(settings, 'GEMINI_API_KEY') or not settings.GEMINI_API_KEY:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Server configuration error: Gemini API key not set'
                }, status=500)

            # Configure Gemini
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # Get form data
            session_id = request.POST.get('session_id')
            message = request.POST.get('message', '').strip()
            files = request.FILES.getlist('files')
            
            # Validate input
            if not message and not files:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Message or file upload is required'
                }, status=400)

            # Get or create chat session
            chat_session = None
            if session_id:
                try:
                    chat_session = ChatSession.objects.get(id=session_id, user=request.user)
                except ChatSession.DoesNotExist:
                    pass

            if not chat_session:
                title = message[:50] if message else "New Chat with Files" if files else "New Chat"
                chat_session = ChatSession.objects.create(
                    user=request.user,
                    title=title
                )

            # Save user message
            chat_message = ChatMessage.objects.create(
                session=chat_session,
                message=message,
                response='',
                is_user=True
            )

            # Handle file uploads
            uploaded_files = []
            for file in files:
                # Validate file size (10MB max)
                if file.size > 10 * 1024 * 1024:
                    continue
                
                # Save file to storage
                file_path = default_storage.save(
                    f'uploads/{request.user.id}/{file.name}',
                    ContentFile(file.read())
                )
                
                # Create file record
                uploaded_file = UploadedFile.objects.create(
                    message=chat_message,
                    file=file_path,
                    content_type=file.content_type,
                    original_name=file.name
                )
                uploaded_files.append(uploaded_file)

            # Prepare message content for Gemini
            content_parts = []
            
            # Add text if provided
            if message:
                content_parts.append(message)
            
            # Add image data if uploaded
            for uploaded_file in uploaded_files:
                if is_image_file(uploaded_file.file):
                    image_path = Path(settings.MEDIA_ROOT) / uploaded_file.file.name
                    image_part = {
                        "mime_type": uploaded_file.content_type,
                        "data": image_path.read_bytes()
                    }
                    content_parts.append(image_part)

            # Select the appropriate model based on content
            model_to_use = None
            available_models = [m.name for m in genai.list_models()]
            
            if any('gemini-1.5-pro' in m for m in available_models):
                model_to_use = 'gemini-1.5-pro-latest'
            elif any('gemini-pro-vision' in m for m in available_models) and uploaded_files:
                model_to_use = 'gemini-pro-vision'
            elif any('gemini-pro' in m for m in available_models):
                model_to_use = 'gemini-pro'
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No compatible Gemini model available'
                }, status=503)

            # Initialize the model
            model = genai.GenerativeModel(model_to_use)
            
            # Prepare chat history
            previous_messages = ChatMessage.objects.filter(
                session=chat_session
            ).order_by('-created_at')[:6]
            
            # Start chat with history
            chat = model.start_chat(history=[])
            for msg in reversed(previous_messages):
                role = "user" if msg.is_user else "model"
                parts = [msg.message] if msg.is_user else [msg.response]
                chat.history.append({
                    "role": role,
                    "parts": parts
                })

            # Get response from Gemini
            if len(content_parts) == 1 and isinstance(content_parts[0], str):
                # Text-only message
                response = chat.send_message(content_parts[0])
            else:
                # Message with images or mixed content
                response = chat.send_message(content_parts)
            
            ai_response = response.text

            cleaned_response = ai_response.replace('*', '')

            # Save AI response
            ChatMessage.objects.create(
                session=chat_session,
                message=message,
                response=cleaned_response,
                is_user=False
            )

            return JsonResponse({
                'status': 'success',
                'response': cleaned_response,
                'session_id': chat_session.id,
                'files': [{
                    'url': file.file.url,
                    'name': file.original_name,
                    'is_image': is_image_file(file.file)
                } for file in uploaded_files]
            })

        except Exception as e:
            traceback.print_exc()
            return JsonResponse({
                'status': 'error',
                'message': f'Error processing request: {str(e)}'
            }, status=500)

    return JsonResponse({
        'status': 'error',
        'message': 'Invalid request method'
    }, status=400)

@login_required
def delete_session(request, session_id):
    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
        session.delete()
        django_messages.success(request, 'Session deleted successfully')
    except ChatSession.DoesNotExist:
        django_messages.error(request, 'Chat session not found')
    except Exception as e:
        django_messages.error(request, f'Error deleting session: {str(e)}')
    return redirect('index')  

def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('index')
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form})

def custom_logout(request):
    if request.method == 'POST':
        logout(request)
        return redirect('index')
    # If GET request, show confirmation page
    return render(request, 'registration/logout.html')
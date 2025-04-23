from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('chat/', views.chat, name='chat'),  # For new chats (no arguments)
    path('chat/<int:session_id>/', views.chat, name='chat_session'),  # For existing chats
    path('new-chat/', views.new_chat, name='new_chat'),
    path('send-message/', views.send_message, name='send_message'),
    path('delete-session/<int:session_id>/', views.delete_session, name='delete_session'),
    path('sessions/', views.chat_sessions, name='chat_sessions'),
]
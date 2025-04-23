from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import os
from django.core.validators import FileExtensionValidator

def user_upload_path(instance, filename):
    """Generate upload path based on user ID and timestamp"""
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    return f'user_uploads/{instance.message.session.user.id}/{timestamp}_{filename}'

class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    title = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'

    def __str__(self):
        return f"{self.user.username} - {self.title}"

    def get_message_count(self):
        return self.messages.count()

class ChatMessage(models.Model):
    session = models.ForeignKey(
        ChatSession, 
        on_delete=models.CASCADE, 
        related_name='messages'
    )
    message = models.TextField(blank=True)
    response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_user = models.BooleanField(default=True)
    has_attachments = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'

    def __str__(self):
        prefix = "User" if self.is_user else "AI"
        return f"{prefix} message in {self.session.title}"

    def save(self, *args, **kwargs):
        # Update parent session's updated_at when saving a message
        self.session.updated_at = timezone.now()
        self.session.save()
        super().save(*args, **kwargs)

class UploadedFile(models.Model):
    VALID_FILE_EXTENSIONS = [
        'jpg', 'jpeg', 'png', 'gif',  # Images
        'pdf', 'doc', 'docx', 'txt'    # Documents
    ]

    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(
        upload_to=user_upload_path,
        validators=[
            FileExtensionValidator(allowed_extensions=VALID_FILE_EXTENSIONS)
        ]
    )
    content_type = models.CharField(max_length=100)
    original_name = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_size = models.PositiveIntegerField()

    class Meta:
        ordering = ['uploaded_at']
        verbose_name = 'Uploaded File'
        verbose_name_plural = 'Uploaded Files'

    def __str__(self):
        return f"{self.original_name} ({self.get_file_size_display()})"

    def save(self, *args, **kwargs):
        # Set file size on upload
        if not self.file_size and self.file:
            self.file_size = self.file.size
        
        # Mark parent message as having attachments
        if not self.message.has_attachments:
            self.message.has_attachments = True
            self.message.save()
        
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Delete the file from storage when model is deleted"""
        storage, path = self.file.storage, self.file.path
        super().delete(*args, **kwargs)
        storage.delete(path)

    def get_file_size_display(self):
        """Human-readable file size"""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    def is_image(self):
        """Check if file is an image"""
        return self.content_type.startswith('image/')

    def get_file_extension(self):
        """Get file extension in lowercase"""
        return os.path.splitext(self.original_name)[1][1:].lower()
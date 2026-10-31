from pathlib import Path
from rest_framework import serializers
from .models import Bid

class BidSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bid
        fields = ["id", "title", "bid_number", "source", "source_pdf", "status", "extracted_text", "extracted_metadata", "processing_error", "created_at", "updated_at"]
        read_only_fields = ["status", "extracted_metadata", "processing_error", "created_at", "updated_at"]

    def validate_source_pdf(self, file):
        if Path(file.name).suffix.lower() != ".pdf":
            raise serializers.ValidationError("Upload the original GeM bid document as a PDF (.pdf).")
        if file.size > 50 * 1024 * 1024:
            raise serializers.ValidationError("GeM bid PDF files must be 50 MB or smaller.")
        if file.content_type not in ("application/pdf", "application/octet-stream", ""):
            raise serializers.ValidationError("The uploaded file type is not PDF. Choose the original GeM bid PDF.")
        header = file.read(5)
        file.seek(0)
        if header != b"%PDF-":
            raise serializers.ValidationError("The file contents are not a valid PDF signature. It may be another file renamed as .pdf.")
        return file

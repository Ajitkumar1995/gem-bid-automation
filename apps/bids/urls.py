from django.urls import path
from .views import bid_dashboard, bid_link_list, complete_bid, queue_bid_links, view_bid_pdf, view_linked_file
from apps.generation.views import prepare_bid

urlpatterns = [
    path("", bid_dashboard, name="bid-dashboard"),
    path("<int:bid_id>/complete/", complete_bid, name="bid-complete"),
    path("<int:bid_id>/links/", bid_link_list, name="bid-link-list"),
    path("<int:bid_id>/links/download/", queue_bid_links, name="bid-link-download"),
    path("<int:bid_id>/file/", view_bid_pdf, name="bid-pdf-view"),
    path("<int:bid_id>/prepare/", prepare_bid, name="bid-prepare"),
    path("<int:bid_id>/linked/<int:document_id>/file/", view_linked_file, name="linked-file-view"),
]

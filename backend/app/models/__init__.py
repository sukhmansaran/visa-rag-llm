"""Database models."""

from app.models.user import User
from app.models.profile import Profile
from app.models.document import Document
from app.models.user_document import UserDocument
from app.models.source import Source
from app.models.vector_chunk import VectorChunk
from app.models.chat_message import ChatMessage
from app.models.change import Change
from app.models.payment import Payment
from app.models.review import Review
from app.models.notification import Notification
from app.models.watchlist import Watchlist

# Tourist visa feature models
from app.models.tourist_destination import TouristDestination
from app.models.tourist_visa_info import TouristVisaInfo
from app.models.travel_cost import TravelCost
from app.models.travel_package import TravelPackage
from app.models.travel_itinerary import TravelItinerary

# Application Tracker Feature
from app.models.application import ApplicationTracker

# Crawler Pipeline models
from app.models.aggregator_portal import AggregatorPortal
from app.models.seed_url import SeedURL
from app.models.crawl_job import CrawlJob
from app.models.crawled_page import CrawledPage
from app.models.program_record import ProgramRecord

# Versioning & Ingestion Models (Stage B2)
from app.models.ingestion_run import IngestionRun
from app.models.logical_document import LogicalDocument
from app.models.document_version import DocumentVersion
from app.models.current_document_pointer import CurrentDocumentPointer
from app.models.legacy_document_version_mapping import LegacyDocumentVersionMapping
from app.models.version_indexing_operation import VersionIndexingOperation
from app.models.document_change import DocumentChange
from app.models.migration_unmapped_record import MigrationUnmappedRecord

__all__ = [
    "User",
    "Profile",
    "Document",
    "UserDocument",
    "Source",
    "VectorChunk",
    "ChatMessage",
    "Change",
    "Payment",
    "Review",
    "Notification",
    "Watchlist",
    "TouristDestination",
    "TouristVisaInfo",
    "TravelCost",
    "TravelPackage",
    "TravelItinerary",
    "ApplicationTracker",
    "AggregatorPortal",
    "SeedURL",
    "CrawlJob",
    "CrawledPage",
    "ProgramRecord",
    "IngestionRun",
    "LogicalDocument",
    "DocumentVersion",
    "CurrentDocumentPointer",
    "LegacyDocumentVersionMapping",
    "VersionIndexingOperation",
    "DocumentChange",
    "MigrationUnmappedRecord",
]

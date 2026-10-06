"""
Portal-specific extraction configurations for known aggregator portals.

Maps portal domains to ExtractionConfig instances with CSS selectors,
JSON-LD patterns, and HTML patterns tailored to each portal's page structure.
"""

from app.services.crawler.types import ExtractionConfig

# Registry: domain -> ExtractionConfig
PORTAL_EXTRACTION_CONFIGS: dict[str, ExtractionConfig] = {
    # Studyportals (mastersportal, bachelorsportal, phdportal)
    "mastersportal.com": ExtractionConfig(
        css_selectors={
            "program_name": "h1.StudyName",
            "university_name": ".OrganisationName a",
            "tuition_fee": ".TuitionFee .Value",
            "duration": ".Duration .Value",
            "location": ".Location",
            "degree_level": ".StudyTypeLabel",
        },
        json_ld_patterns=["Course", "EducationalOrganization"],
    ),
    "bachelorsportal.com": ExtractionConfig(
        css_selectors={
            "program_name": "h1.StudyName",
            "university_name": ".OrganisationName a",
            "tuition_fee": ".TuitionFee .Value",
            "duration": ".Duration .Value",
            "location": ".Location",
        },
        json_ld_patterns=["Course", "EducationalOrganization"],
    ),
    "phdportal.com": ExtractionConfig(
        css_selectors={
            "program_name": "h1.StudyName",
            "university_name": ".OrganisationName a",
            "location": ".Location",
        },
        json_ld_patterns=["Course"],
    ),
    # Other countries' portals commented out — Canada-only focus
    # # UCAS (UK)
    # "ucas.com": ExtractionConfig(
    #     css_selectors={
    #         "program_name": "h1.course-header__title",
    #         "university_name": ".course-header__provider",
    #         "ucas_tariff_points": ".entry-requirements__tariff-points",
    #         "duration": ".course-details__duration",
    #         "entry_requirements": ".entry-requirements__content",
    #     },
    #     json_ld_patterns=["Course"],
    # ),
    # # DAAD (Germany)
    # "daad.de": ExtractionConfig(
    #     css_selectors={
    #         "program_name": "h1.c-result-detail__title",
    #         "university_name": ".c-result-detail__university",
    #         "duration": ".c-result-detail__duration",
    #         "language_of_instruction": ".c-result-detail__language",
    #         "application_deadline": ".c-result-detail__deadline",
    #     },
    #     json_ld_patterns=["Course", "EducationalOrganization"],
    # ),
    # EduCanada
    "educanada.ca": ExtractionConfig(
        css_selectors={
            "program_name": "h1",
            "university_name": ".institution-name",
            "location": ".institution-location",
        },
        json_ld_patterns=["Course"],
    ),
    # Hotcourses
    "hotcoursesabroad.com": ExtractionConfig(
        css_selectors={
            "program_name": "h1.course-title",
            "university_name": ".institution-name",
            "tuition_fee": ".course-fee",
            "duration": ".course-duration",
            "location": ".course-location",
        },
        json_ld_patterns=["Course"],
    ),
}


def get_portal_config(domain: str) -> ExtractionConfig | None:
    """Look up extraction config for a domain (checks base domain)."""
    domain = domain.lower()
    if domain in PORTAL_EXTRACTION_CONFIGS:
        return PORTAL_EXTRACTION_CONFIGS[domain]
    # Check if it's a subdomain of a known portal
    for known_domain, config in PORTAL_EXTRACTION_CONFIGS.items():
        if domain.endswith("." + known_domain) or domain == known_domain:
            return config
    return None

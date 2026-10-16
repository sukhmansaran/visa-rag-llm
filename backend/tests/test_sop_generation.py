"""
Unit tests for SOP generation functionality.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.services.sop_generator import (
    generate_sop,
    _detect_country,
    _format_test_scores,
    _build_profile_context,
    SOP_TEMPLATES
)
from app.models.profile import Profile


FULL_SOP = "Statement of Purpose. " + "I am applying to this program because of my background. " * 40


class TestCountryDetection:
    """Test country detection from university names."""
    
    # Other countries commented out — Canada-only focus
    # def test_detect_us_universities(self):
    #     assert _detect_country("Stanford University") == "US"
    #     assert _detect_country("MIT") == "US"
    #     assert _detect_country("Harvard University") == "US"
    #     assert _detect_country("UC Berkeley") == "US"
    
    # def test_detect_uk_universities(self):
    #     assert _detect_country("University of Oxford") == "UK"
    #     assert _detect_country("Cambridge University") == "UK"
    #     assert _detect_country("Imperial College London") == "UK"
    #     assert _detect_country("LSE") == "UK"
    
    def test_detect_canada_universities(self):
        assert _detect_country("University of Toronto") == "Canada"
        assert _detect_country("McGill University") == "Canada"
        assert _detect_country("UBC") == "Canada"
    
    # def test_detect_australia_universities(self):
    #     assert _detect_country("University of Melbourne") == "Australia"
    #     assert _detect_country("University of Sydney") == "Australia"
    #     assert _detect_country("UNSW") == "Australia"
    
    def test_detect_unknown_university(self):
        assert _detect_country("Unknown University") == "default"


class TestTestScoreFormatting:
    """Test test score formatting."""
    
    def test_format_gre_scores(self):
        scores = {
            "gre": {"verbal": 160, "quantitative": 168, "analytical": 4.5}
        }
        result = _format_test_scores(scores)
        assert "GRE" in result
        assert "160" in result
        assert "168" in result
    
    def test_format_single_score(self):
        scores = {"toefl": 108}
        result = _format_test_scores(scores)
        assert "TOEFL: 108" in result
    
    def test_format_multiple_tests(self):
        scores = {
            "gre": {"verbal": 160, "quantitative": 168},
            "toefl": 108
        }
        result = _format_test_scores(scores)
        assert "GRE" in result
        assert "TOEFL" in result
    
    def test_format_empty_scores(self):
        result = _format_test_scores(None)
        assert result == "Not specified"
        
        result = _format_test_scores({})
        assert result == "Not specified"


class TestProfileContext:
    """Test profile context building."""
    
    def test_build_complete_profile(self):
        profile = Profile(
            user_id=1,
            first_name="John",
            last_name="Doe",
            education_level="bachelor",
            field_of_study="Computer Science",
            gpa=3.8,
            test_scores={"gre": {"verbal": 160, "quantitative": 168}},
            work_experience=2
        )
        
        context = _build_profile_context(
            profile=profile,
            university="University of Toronto",
            program="MS CS",
            additional_info="AI research"
        )
        
        assert context["name"] == "John Doe"
        assert context["education_level"] == "bachelor"
        assert context["field_of_study"] == "Computer Science"
        assert context["gpa"] == 3.8
        assert context["work_experience"] == "2 years"
        assert context["university"] == "University of Toronto"
        assert context["program"] == "MS CS"
        assert context["additional_info"] == "AI research"
    
    def test_build_minimal_profile(self):
        profile = Profile(
            user_id=1,
            education_level="bachelor",
            field_of_study="Engineering"
        )
        
        context = _build_profile_context(
            profile=profile,
            university="Test University",
            program="Test Program",
            additional_info=None
        )
        
        assert context["name"] == "Applicant"
        assert context["gpa"] == "Not specified"
        assert context["work_experience"] == "0 years"
        assert context["additional_info"] == "None provided"


class TestSOPTemplates:
    """Test SOP template structure."""
    
    def test_all_templates_have_required_fields(self):
        required_fields = ["max_words", "key_sections", "tips"]
        
        for country, template in SOP_TEMPLATES.items():
            for field in required_fields:
                assert field in template, f"{country} template missing {field}"
    
    # Other countries commented out — Canada-only focus
    # def test_us_template_word_limit(self):
    #     assert SOP_TEMPLATES["US"]["max_words"] == 1000
    
    # def test_uk_template_word_limit(self):
    #     assert SOP_TEMPLATES["UK"]["max_words"] == 500
    
    def test_canada_template_word_limit(self):
        assert SOP_TEMPLATES["Canada"]["max_words"] == 1000
    
    # def test_australia_template_word_limit(self):
    #     assert SOP_TEMPLATES["Australia"]["max_words"] == 600


@pytest.mark.asyncio
class TestSOPGeneration:
    """Test SOP generation with mocked LLM."""
    
    @patch('app.services.sop_generator.llm_service.generate_long_text')
    @patch('app.services.sop_generator._retrieve_program_context')
    async def test_generate_sop_success(self, mock_retrieve, mock_llm):
        """Test successful SOP generation."""
        
        # Mock responses
        mock_retrieve.return_value = "Program context from vector store"
        mock_llm.return_value = FULL_SOP
        
        profile = Profile(
            user_id=1,
            first_name="Test",
            last_name="User",
            education_level="bachelor",
            field_of_study="Computer Science",
            gpa=3.8
        )
        
        result = await generate_sop(
            profile=profile,
            university="University of Toronto",
            program="MS in CS",
            additional_info="AI research"
        )
        
        assert result == FULL_SOP
        mock_llm.assert_called_once()
        mock_retrieve.assert_called_once()
    
    @patch('app.services.sop_generator.llm_service.generate_long_text')
    @patch('app.services.sop_generator._retrieve_program_context')
    async def test_generate_sop_without_context(self, mock_retrieve, mock_llm):
        """Test SOP generation when context retrieval fails."""
        
        mock_retrieve.return_value = ""  # No context
        mock_llm.return_value = FULL_SOP
        
        profile = Profile(
            user_id=1,
            first_name="Test",
            last_name="User",
            education_level="bachelor",
            field_of_study="Engineering"
        )
        
        result = await generate_sop(
            profile=profile,
            university="Unknown University",
            program="Test Program"
        )
        
        assert result == FULL_SOP
        mock_llm.assert_called_once()
    
    @patch('app.services.sop_generator.llm_service.generate_long_text')
    @patch('app.services.sop_generator._retrieve_program_context')
    async def test_generate_sop_different_countries(self, mock_retrieve, mock_llm):
        """Test SOP generation for different countries."""
        
        mock_retrieve.return_value = ""
        mock_llm.return_value = FULL_SOP
        
        profile = Profile(
            user_id=1,
            first_name="Test",
            last_name="User",
            education_level="bachelor",
            field_of_study="Business"
        )
        
        # Test Canada
        await generate_sop(profile, "Toronto", "MBA")
        # Other countries commented out — Canada-only focus
        # await generate_sop(profile, "Stanford", "MBA")
        # await generate_sop(profile, "Oxford", "MBA")
        # await generate_sop(profile, "Melbourne", "MBA")
        
        assert mock_llm.call_count == 1


@pytest.mark.asyncio
class TestProgramContextRetrieval:
    """Test program context retrieval from vector store."""
    
    @patch('app.services.sop_generator.retrieval_service.retrieve')
    async def test_retrieve_program_context_success(self, mock_retrieve):
        """Test successful context retrieval."""
        from app.services.sop_generator import _retrieve_program_context
        
        mock_retrieve.return_value = [
            {
                "text": "UofT CS program focuses on AI and ML...",
                "metadata": {"url": "https://utoronto.ca/cs"}
            },
            {
                "text": "Faculty research includes NLP and computer vision...",
                "metadata": {"url": "https://utoronto.ca/faculty"}
            }
        ]
        
        result = await _retrieve_program_context("University of Toronto", "MS CS")
        
        assert "UofT CS program" in result
        assert "utoronto.ca" in result
        mock_retrieve.assert_called_once()
    
    @patch('app.services.sop_generator.retrieval_service.retrieve')
    async def test_retrieve_program_context_empty(self, mock_retrieve):
        """Test context retrieval with no results."""
        from app.services.sop_generator import _retrieve_program_context
        
        mock_retrieve.return_value = []
        
        result = await _retrieve_program_context("Unknown", "Unknown")
        
        assert result == ""
    
    @patch('app.services.sop_generator.retrieval_service.retrieve')
    async def test_retrieve_program_context_error(self, mock_retrieve):
        """Test context retrieval with error."""
        from app.services.sop_generator import _retrieve_program_context
        
        mock_retrieve.side_effect = Exception("Vector store error")
        
        result = await _retrieve_program_context("Test", "Test")
        
        assert result == ""  # Should return empty string on error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------- 2026-10-15 review (B4)

@pytest.mark.asyncio
@patch('app.services.sop_generator._retrieve_program_context', new_callable=AsyncMock, return_value="")
async def test_a_stub_is_retried_then_refused(mock_retrieve):
    """One review run returned a 26-word 'SOP'; the generator must not hand that to the user."""
    from app.services.sop_generator import SOP_MAX_ATTEMPTS, SOPGenerationError

    profile = Profile(user_id=1, education_level="bachelor", field_of_study="CS")
    with patch('app.services.sop_generator.llm_service.generate_long_text', new_callable=AsyncMock,
               return_value="As a driven professional, I am excited to apply.") as mock_llm:
        with pytest.raises(SOPGenerationError):
            await generate_sop(profile, "University of Toronto", "MSc Computer Science")
    assert mock_llm.call_count == SOP_MAX_ATTEMPTS


@pytest.mark.asyncio
@patch('app.services.sop_generator._retrieve_program_context', new_callable=AsyncMock, return_value="")
async def test_a_stub_followed_by_a_full_draft_returns_the_draft(mock_retrieve):
    profile = Profile(user_id=1, education_level="bachelor", field_of_study="CS")
    with patch('app.services.sop_generator.llm_service.generate_long_text', new_callable=AsyncMock,
               side_effect=["Too short.", FULL_SOP]) as mock_llm:
        assert await generate_sop(profile, "University of Toronto", "MSc Computer Science") == FULL_SOP
    assert mock_llm.call_count == 2
    kwargs = mock_llm.call_args.kwargs
    assert kwargs["max_tokens"] <= 1500 and kwargs["temperature"] <= 0.5 and kwargs["role"] == "sop"


@pytest.mark.asyncio
async def test_long_text_is_collected_from_a_stream_not_one_timed_request(monkeypatch):
    """generate_long_text must use the stream (idle timeout per chunk), never the total-time request."""
    from app.services.llm import llm_service

    async def stream(**_):
        for word in ["Statement ", "of ", "purpose."]:
            yield word

    async def must_not_be_called(**_):
        raise AssertionError("the non-streaming call has a total-time limit")

    monkeypatch.setattr(llm_service, "generate_answer_stream", stream)
    monkeypatch.setattr(llm_service, "generate_answer", must_not_be_called)
    assert await llm_service.generate_long_text(system_prompt="s", user_prompt="u") == "Statement of purpose."

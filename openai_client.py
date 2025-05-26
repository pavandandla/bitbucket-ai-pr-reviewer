import time
import json
import logging
import openai
from openai import OpenAI

# Configure logging
logger = logging.getLogger()

class OpenAIClient:
    """Client for OpenAI API interactions."""
    
    def __init__(self, api_key=None, model="gpt-4-1106-preview"):
        """
        Initialize the OpenAI API client.
        
        Args:
            api_key (str): OpenAI API key
            model (str): OpenAI model to use
            
        Raises:
            ValueError: If API key is not provided
        """
        self.api_key = api_key
        self.model = model
        
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")
        
        # Initialize OpenAI client
        self.client = OpenAI(api_key=self.api_key)
    
    def generate_review(self, diff_content, pr_info, max_tokens=30000):
        """
        Generate a code review from PR diff.
        
        Args:
            diff_content (str): PR diff content
            pr_info (dict): Pull request metadata
            max_tokens (int): Maximum tokens to use for the diff
            
        Returns:
            list: Array of review comments
            
        Raises:
            Exception: If API request fails
        """
        try:
            # Truncate diff if necessary
            truncated_diff = self._truncate_diff(diff_content, max_tokens)
            
            # Prepare prompt for OpenAI
            prompt = self._build_prompt(truncated_diff, pr_info)
            
            # Call OpenAI API with exponential backoff for rate limiting
            completion = self._call_with_retry(lambda: self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            ))
            
            response_text = completion.choices[0].message.content.strip()
            
            # Parse response to extract structured comments
            return self._parse_response(response_text)
        except Exception as e:
            logger.error("Error generating review with OpenAI: %s", str(e))
            raise Exception(f"Failed to generate review: {str(e)}")
    
    def _truncate_diff(self, diff_content, max_tokens):
        """
        Truncate diff content to fit within token limits.
        
        Args:
            diff_content (str): PR diff content
            max_tokens (int): Maximum tokens to use
            
        Returns:
            str: Truncated diff content
        """
        # Rough approximation: 1 token ≈ 4 characters for English text
        max_chars = max_tokens * 4
        
        if len(diff_content) <= max_chars:
            return diff_content
        
        # If we need to truncate, try to do it smartly by preserving complete file diffs where possible
        diff_files = diff_content.split('diff --git ')
        
        result = ""
        current_length = 0
        
        # Always include the first file (even if empty)
        for i, file_diff in enumerate(diff_files):
            if i == 0 and not file_diff.strip():
                continue  # Skip empty first element
            
            file_diff_text = file_diff if i == 0 else f"diff --git {file_diff}"
            
            if current_length + len(file_diff_text) > max_chars:
                # If we can't add another full file diff, stop here
                break
            
            result += file_diff_text
            current_length += len(file_diff_text)
        
        # If we couldn't include any files (diff of first file is too large), truncate the first file
        if not result and diff_files:
            first_file = diff_files[0] if diff_files[0].strip() else f"diff --git {diff_files[1]}"
            result = first_file[:max_chars]
        
        return result + "\n[TRUNCATED - Diff too large for complete analysis]"
    
    def _build_prompt(self, diff_content, pr_info):
        """
        Build prompt for OpenAI.
        
        Args:
            diff_content (str): PR diff content
            pr_info (dict): Pull request metadata
            
        Returns:
            str: Formatted prompt
        """
        return f"""You are a senior software engineer reviewing a pull request. 
Please provide constructive feedback on the following code changes for a PR titled: "{pr_info['title']}".
{f"PR Description: {pr_info['description']}\n\n" if pr_info.get('description') else ''}

Focus on:
- Code quality and best practices
- Potential bugs or edge cases
- Security concerns
- Performance issues
- Readability and maintainability

For each issue found, specify the exact file and line number from the diff.
Format your response as a JSON array of objects with the following structure:
[
  {{
    "file": "filename.ext",
    "line": 42, // Line number where the comment should be placed
    "comment": "Your constructive feedback here"
  }}
]

Here's the diff:
```diff
{diff_content}
```"""
    
    def _parse_response(self, response_text):
        """
        Parse OpenAI response into structured comments.
        
        Args:
            response_text (str): Text response from OpenAI
            
        Returns:
            list: Array of review comments
        """
        try:
            # Extract JSON array from response (handle case where GPT might add markdown formatting)
            json_start = response_text.find('[')
            json_end = response_text.rfind(']') + 1
            
            if json_start == -1 or json_end == 0 or json_end <= json_start:
                # If we can't find valid JSON markers, return the full text as a general comment
                return [{
                    "file": None,
                    "line": None,
                    "comment": f"General PR Review:\n\n{response_text}"
                }]
            
            json_str = response_text[json_start:json_end]
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse review as JSON, using text response")
            # Fallback - if parsing fails, return a single general comment
            return [{
                "file": None,
                "line": None,
                "comment": f"General PR Review:\n\n{response_text}"
            }]
    
    def _call_with_retry(self, api_call, max_retries=3, initial_delay=1):
        """
        Call OpenAI API with exponential backoff retry.
        
        Args:
            api_call (callable): Function that makes the API call
            max_retries (int): Maximum number of retries
            initial_delay (int): Initial delay in seconds
            
        Returns:
            object: API response
            
        Raises:
            Exception: If all retries fail
        """
        last_error = None
        delay = initial_delay
        
        for attempt in range(max_retries + 1):
            try:
                return api_call()
            except (openai.RateLimitError, openai.APIError) as e:
                last_error = e
                
                # Check if we've exhausted our retries
                if attempt == max_retries:
                    break
                
                # Calculate delay with exponential backoff
                retry_delay = delay * (2 ** attempt)
                logger.info(f"Rate limited by OpenAI API, retrying after {retry_delay}s delay (attempt {attempt + 1}/{max_retries + 1})")
                
                # Wait for the specified delay
                time.sleep(retry_delay)
            except Exception as e:
                # For other errors, don't retry
                raise e
        
        raise last_error 
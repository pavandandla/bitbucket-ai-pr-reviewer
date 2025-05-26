import time
import base64
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logger = logging.getLogger()

class BitbucketClient:
    """Client for Bitbucket API interactions."""
    
    def __init__(self, username=None, app_password=None):
        """
        Initialize the Bitbucket API client.
        
        Args:
            username (str): Bitbucket username
            app_password (str): Bitbucket app password
        
        Raises:
            ValueError: If credentials are not provided
        """
        self.username = username
        self.app_password = app_password
        
        if not self.username or not self.app_password:
            raise ValueError("Bitbucket credentials not provided")
        
        # Create authentication header
        auth_str = f"{self.username}:{self.app_password}"
        self.auth_header = f"Basic {base64.b64encode(auth_str.encode()).decode()}"
        
        # Setup session with retry logic
        self.session = self._create_session()
    
    def _create_session(self):
        """
        Create a requests session with retry configuration.
        
        Returns:
            requests.Session: Configured session
        """
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Set default headers
        session.headers.update({
            "Authorization": self.auth_header,
            "Content-Type": "application/json"
        })
        
        return session
    
    def get_pr_diff(self, workspace, repo_slug, pr_id):
        """
        Fetch PR diff from Bitbucket.
        
        Args:
            workspace (str): Bitbucket workspace slug
            repo_slug (str): Repository slug
            pr_id (int): Pull request ID
        
        Returns:
            str: PR diff content
            
        Raises:
            Exception: If API request fails
        """
        try:
            url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/diff"
            headers = {"Accept": "text/plain"}
            
            response = self.session.get(url, headers=headers)
            response.raise_for_status()
            
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error("Error fetching PR diff: %s", str(e))
            raise Exception(f"Failed to fetch PR diff: {str(e)}")
    
    def get_pr_changed_files(self, workspace, repo_slug, pr_id):
        """
        Get all changed files in a PR.
        
        Args:
            workspace (str): Bitbucket workspace slug
            repo_slug (str): Repository slug
            pr_id (int): Pull request ID
        
        Returns:
            list: Array of changed files
            
        Raises:
            Exception: If API request fails
        """
        try:
            files = []
            url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/diffstat"
            
            # Handle pagination
            while url:
                response = self.session.get(url)
                response.raise_for_status()
                data = response.json()
                
                # Add files from current page
                files.extend(data.get("values", []))
                
                # Get next page URL if it exists
                url = data.get("next")
            
            return files
        except requests.exceptions.RequestException as e:
            logger.error("Error fetching changed files: %s", str(e))
            raise Exception(f"Failed to fetch changed files: {str(e)}")
    
    def post_pr_comment(self, workspace, repo_slug, pr_id, comment):
        """
        Post a comment on a pull request.
        
        Args:
            workspace (str): Bitbucket workspace slug
            repo_slug (str): Repository slug
            pr_id (int): Pull request ID
            comment (dict): Comment object with content and optional inline info
            
        Returns:
            dict: Comment response data
            
        Raises:
            Exception: If API request fails
        """
        try:
            url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments"
            
            response = self.session.post(url, json=comment)
            
            # Check if rate limited
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                logger.info(f"Rate limited by Bitbucket API, retrying after {retry_after} seconds")
                time.sleep(retry_after)
                # Retry the request
                response = self.session.post(url, json=comment)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error("Error posting comment: %s", str(e))
            raise Exception(f"Failed to post comment: {str(e)}")
    
    def post_pr_comments(self, workspace, repo_slug, pr_id, comments):
        """
        Post multiple comments on a pull request with rate limiting.
        
        Args:
            workspace (str): Bitbucket workspace slug
            repo_slug (str): Repository slug
            pr_id (int): Pull request ID
            comments (list): Array of comment objects
            
        Returns:
            list: Array of comment response data
        """
        results = []
        
        for comment in comments:
            try:
                # Format comment for Bitbucket API
                comment_data = {
                    "content": {
                        "raw": comment.get("content") or f"🤖 **AI Code Review**\n\n{comment.get('comment')}"
                    }
                }
                
                # Add inline information if available
                if comment.get("file") and comment.get("line"):
                    comment_data["inline"] = {
                        "path": comment["file"],
                        "to": comment["line"]
                    }
                
                # Post comment
                result = self.post_pr_comment(workspace, repo_slug, pr_id, comment_data)
                results.append(result)
                
                # Throttle requests to avoid rate limits
                time.sleep(0.5)
            except Exception as e:
                logger.error("Error posting comment: %s", str(e))
                # Continue with other comments if one fails
        
        return results 
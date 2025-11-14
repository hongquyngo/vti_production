# utils/s3_utils.py
"""
S3 Utilities for file upload/download - REFACTORED
Fixed: Logo path handling, error recovery, fallback mechanisms
"""

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import os
from io import BytesIO
from .config import AWS_CONFIG

logger = logging.getLogger(__name__)


class S3Manager:
    """Manager for S3 operations with enhanced error handling"""
    
    def __init__(self):
        """Initialize S3 client with configuration"""
        self.bucket_name = AWS_CONFIG.get('bucket_name', 'prostech-erp-dev')
        self.app_prefix = AWS_CONFIG.get('app_prefix', 'streamlit-app')
        self.region = AWS_CONFIG.get('region', 'ap-southeast-1')
        
        try:
            # Initialize S3 client
            self.s3_client = boto3.client(
                's3',
                region_name=self.region,
                aws_access_key_id=AWS_CONFIG.get('access_key_id'),
                aws_secret_access_key=AWS_CONFIG.get('secret_access_key')
            )
            
            # Test connection
            self._test_connection()
            logger.info(f"✅ S3 client initialized for bucket: {self.bucket_name}")
            
        except NoCredentialsError:
            logger.error("❌ AWS credentials not found")
            raise ValueError("AWS credentials not configured. Please check your configuration.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize S3 client: {e}")
            raise
    
    def _test_connection(self):
        """Test S3 connection by checking bucket exists"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = int(e.response['Error']['Code'])
            if error_code == 404:
                logger.error(f"Bucket {self.bucket_name} not found")
                raise ValueError(f"S3 bucket '{self.bucket_name}' does not exist")
            elif error_code == 403:
                logger.error(f"Access denied to bucket {self.bucket_name}")
                raise ValueError(f"Access denied to S3 bucket '{self.bucket_name}'")
            else:
                raise
    
    def upload_pdf(self, pdf_bytes: bytes, filename: str, 
                   metadata: Optional[Dict[str, str]] = None,
                   folder: str = "production/material-issues") -> Dict[str, Any]:
        """
        Upload PDF to S3 with retry mechanism
        
        Args:
            pdf_bytes: PDF file content as bytes
            filename: Name of the file
            metadata: Optional metadata to attach
            folder: S3 folder path
            
        Returns:
            Dictionary with upload details including URL
        """
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Create full S3 key
                date_folder = datetime.now().strftime('%Y/%m/%d')
                s3_key = f"{self.app_prefix}/{folder}/{date_folder}/{filename}"
                
                # Prepare metadata
                upload_metadata = {
                    'upload_timestamp': datetime.now().isoformat(),
                    'content_type': 'application/pdf',
                    'app': 'production_module',
                    'retry_count': str(retry_count)
                }
                if metadata:
                    upload_metadata.update(metadata)
                
                # Upload to S3
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=pdf_bytes,
                    ContentType='application/pdf',
                    Metadata=upload_metadata,
                    ServerSideEncryption='AES256'  # Enable encryption
                )
                
                # Generate presigned URL (valid for 7 days)
                presigned_url = self.generate_presigned_url(s3_key, expiry_days=7)
                
                # Generate permanent URL (requires public access or CloudFront)
                permanent_url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{s3_key}"
                
                logger.info(f"✅ PDF uploaded successfully: {s3_key}")
                
                return {
                    'success': True,
                    'bucket': self.bucket_name,
                    'key': s3_key,
                    'filename': filename,
                    'size': len(pdf_bytes),
                    'presigned_url': presigned_url,
                    'permanent_url': permanent_url,
                    'upload_time': datetime.now().isoformat()
                }
                
            except ClientError as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"Failed to upload PDF after {max_retries} retries: {e}")
                    return {
                        'success': False,
                        'error': str(e),
                        'retries': retry_count
                    }
                else:
                    logger.warning(f"Upload attempt {retry_count} failed, retrying...")
                    continue
    
    def generate_presigned_url(self, s3_key: str, expiry_days: int = 7) -> Optional[str]:
        """
        Generate presigned URL for S3 object
        
        Args:
            s3_key: S3 object key
            expiry_days: Number of days until URL expires
            
        Returns:
            Presigned URL string or None if failed
        """
        try:
            expiry_seconds = expiry_days * 24 * 60 * 60
            
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': s3_key
                },
                ExpiresIn=expiry_seconds
            )
            
            return url
            
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None
    
    def download_pdf(self, s3_key: str) -> Optional[bytes]:
        """
        Download PDF from S3 with retry
        
        Args:
            s3_key: S3 object key
            
        Returns:
            PDF content as bytes or None if failed
        """
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                response = self.s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
                
                pdf_bytes = response['Body'].read()
                logger.info(f"✅ Downloaded PDF from S3: {s3_key}")
                
                return pdf_bytes
                
            except ClientError as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"Failed to download PDF after {max_retries} retries: {e}")
                    return None
                else:
                    logger.warning(f"Download attempt {retry_count} failed, retrying...")
    
    def list_pdfs(self, prefix: str = None, max_items: int = 100) -> List[Dict]:
        """
        List PDFs in S3 bucket
        
        Args:
            prefix: Filter by prefix
            max_items: Maximum number of items to return
            
        Returns:
            List of PDF objects
        """
        try:
            if prefix is None:
                prefix = f"{self.app_prefix}/production/material-issues/"
            
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_items
            )
            
            if 'Contents' not in response:
                return []
            
            pdfs = []
            for obj in response['Contents']:
                if obj['Key'].endswith('.pdf'):
                    pdfs.append({
                        'key': obj['Key'],
                        'filename': os.path.basename(obj['Key']),
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat(),
                    })
            
            return pdfs
            
        except ClientError as e:
            logger.error(f"Failed to list PDFs: {e}")
            return []
    
    def delete_pdf(self, s3_key: str) -> bool:
        """
        Delete PDF from S3
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            logger.info(f"✅ Deleted PDF from S3: {s3_key}")
            return True
            
        except ClientError as e:
            logger.error(f"Failed to delete PDF: {e}")
            return False
    
    def get_object_metadata(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for S3 object
        
        Args:
            s3_key: S3 object key
            
        Returns:
            Metadata dictionary or None if failed
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            return {
                'content_type': response.get('ContentType'),
                'content_length': response.get('ContentLength'),
                'last_modified': response.get('LastModified').isoformat() if response.get('LastModified') else None,
                'metadata': response.get('Metadata', {}),
                'etag': response.get('ETag')
            }
            
        except ClientError as e:
            logger.error(f"Failed to get object metadata: {e}")
            return None
    
    def check_object_exists(self, s3_key: str) -> bool:
        """
        Check if object exists in S3
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if exists, False otherwise
        """
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                logger.error(f"Error checking object existence: {e}")
                return False


# ==================== ENHANCED LOGO FUNCTIONS ====================

def get_company_logo_from_s3_enhanced(company_id: int, logo_path: Optional[str] = None) -> Optional[bytes]:
    """
    Enhanced logo fetching with multiple fallback strategies
    
    Args:
        company_id: Company ID
        logo_path: Path to logo in S3 (may be partial or incorrect)
        
    Returns:
        Logo bytes or None if not found
    """
    try:
        logger.info(f"Fetching logo for company {company_id}: {logo_path}")
        
        # Initialize S3 client
        s3_manager = S3Manager()
        
        # Strategy 1: Try direct path if provided
        if logo_path:
            # Clean up path
            if logo_path.startswith('/'):
                logo_path = logo_path[1:]
            
            # Try different path formats
            paths_to_try = [
                logo_path,  # As provided
                f"company-logo/{logo_path}" if not logo_path.startswith('company-logo/') else logo_path,
                f"company-logo/{os.path.basename(logo_path)}",  # Just filename in company-logo folder
            ]
            
            for path in paths_to_try:
                try:
                    if s3_manager.check_object_exists(path):
                        response = s3_manager.s3_client.get_object(
                            Bucket=s3_manager.bucket_name,
                            Key=path
                        )
                        logo_bytes = response['Body'].read()
                        logger.info(f"✅ Logo found at: {path} ({len(logo_bytes)} bytes)")
                        return logo_bytes
                except ClientError:
                    continue
        
        # Strategy 2: Search by pattern matching
        logger.info(f"Direct path failed, searching for company {company_id} logo by pattern")
        
        # List all files in company-logo folder
        try:
            response = s3_manager.s3_client.list_objects_v2(
                Bucket=s3_manager.bucket_name,
                Prefix="company-logo/",
                MaxKeys=1000
            )
            
            if 'Contents' in response:
                # Try to find logo by company_id in filename
                for obj in response['Contents']:
                    key = obj['Key']
                    filename = os.path.basename(key).lower()
                    
                    # Check various patterns
                    patterns = [
                        str(company_id),  # Company ID in filename
                        f"company_{company_id}",
                        f"logo_{company_id}",
                        f"{company_id}_",
                    ]
                    
                    for pattern in patterns:
                        if pattern in filename:
                            logger.info(f"Found potential logo by pattern: {key}")
                            try:
                                logo_response = s3_manager.s3_client.get_object(
                                    Bucket=s3_manager.bucket_name,
                                    Key=key
                                )
                                logo_bytes = logo_response['Body'].read()
                                logger.info(f"✅ Logo retrieved by pattern: {key} ({len(logo_bytes)} bytes)")
                                return logo_bytes
                            except ClientError as e:
                                logger.warning(f"Failed to get logo {key}: {e}")
                                continue
        
        except ClientError as e:
            logger.error(f"Failed to list company logos: {e}")
        
        # Strategy 3: Try legacy naming conventions based on screenshot
        legacy_patterns = [
            f"company-logo/{company_id}*",  # Any file starting with company ID
            f"company-logo/*{company_id}*",  # Any file containing company ID
        ]
        
        for pattern in legacy_patterns:
            try:
                # Use prefix and then filter
                prefix = pattern.split('*')[0]
                response = s3_manager.s3_client.list_objects_v2(
                    Bucket=s3_manager.bucket_name,
                    Prefix=prefix,
                    MaxKeys=100
                )
                
                if 'Contents' in response:
                    for obj in response['Contents']:
                        if str(company_id) in obj['Key']:
                            try:
                                logo_response = s3_manager.s3_client.get_object(
                                    Bucket=s3_manager.bucket_name,
                                    Key=obj['Key']
                                )
                                logo_bytes = logo_response['Body'].read()
                                logger.info(f"✅ Logo found with legacy pattern: {obj['Key']}")
                                return logo_bytes
                            except ClientError:
                                continue
            except Exception as e:
                logger.warning(f"Legacy pattern search failed: {e}")
        
        logger.warning(f"No logo found for company {company_id} after trying all strategies")
        return None
        
    except Exception as e:
        logger.error(f"Unexpected error fetching logo for company {company_id}: {e}")
        return None


def get_company_logo_from_s3(company_id: int, logo_path: str) -> Optional[bytes]:
    """
    Legacy function - redirects to enhanced version
    Kept for backward compatibility
    """
    return get_company_logo_from_s3_enhanced(company_id, logo_path)


def upload_company_logo_to_s3(company_id: int, logo_bytes: bytes, 
                              filename: Optional[str] = None) -> Optional[str]:
    """
    Upload company logo to S3 with proper naming convention
    
    Args:
        company_id: Company ID
        logo_bytes: Logo image bytes
        filename: Optional filename (will generate if not provided)
        
    Returns:
        S3 key path or None if failed
    """
    try:
        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            # Match the pattern seen in S3 screenshot
            filename = f"{timestamp}-company{company_id}-logo.png"
        
        # Ensure filename has proper extension
        if not any(filename.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.svg']):
            # Detect image type from bytes (basic detection)
            if logo_bytes[:4] == b'\x89PNG':
                filename += '.png'
            elif logo_bytes[:2] == b'\xff\xd8':
                filename += '.jpg'
            else:
                filename += '.png'  # Default
        
        # Create S3 key
        s3_key = f"company-logo/{filename}"
        
        logger.info(f"Uploading logo for company {company_id}: {s3_key}")
        
        # Initialize S3 client
        s3_manager = S3Manager()
        
        # Determine content type
        content_type = 'image/png'
        if filename.endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'
        elif filename.endswith('.svg'):
            content_type = 'image/svg+xml'
        
        # Upload to S3 with retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                s3_manager.s3_client.put_object(
                    Bucket=s3_manager.bucket_name,
                    Key=s3_key,
                    Body=logo_bytes,
                    ContentType=content_type,
                    Metadata={
                        'company_id': str(company_id),
                        'upload_timestamp': datetime.now().isoformat(),
                        'attempt': str(attempt + 1)
                    },
                    ServerSideEncryption='AES256'
                )
                
                logger.info(f"✅ Logo uploaded successfully: {s3_key}")
                return s3_key
                
            except ClientError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Upload attempt {attempt + 1} failed, retrying...")
                    continue
                else:
                    logger.error(f"Failed to upload logo after {max_retries} attempts: {e}")
                    return None
        
    except Exception as e:
        logger.error(f"Unexpected error uploading logo: {e}")
        return None


def list_company_logos(company_id: Optional[int] = None) -> List[Dict]:
    """
    List all company logos in S3
    
    Args:
        company_id: Optional filter by company ID
        
    Returns:
        List of logo objects with metadata
    """
    try:
        s3_manager = S3Manager()
        
        response = s3_manager.s3_client.list_objects_v2(
            Bucket=s3_manager.bucket_name,
            Prefix="company-logo/",
            MaxKeys=1000
        )
        
        if 'Contents' not in response:
            return []
        
        logos = []
        for obj in response['Contents']:
            # Filter by company_id if provided
            if company_id:
                if not str(company_id) in obj['Key']:
                    continue
            
            # Get metadata
            try:
                head_response = s3_manager.s3_client.head_object(
                    Bucket=s3_manager.bucket_name,
                    Key=obj['Key']
                )
                metadata = head_response.get('Metadata', {})
            except:
                metadata = {}
            
            logos.append({
                'key': obj['Key'],
                'filename': os.path.basename(obj['Key']),
                'size': obj['Size'],
                'last_modified': obj['LastModified'].isoformat(),
                'company_id': metadata.get('company_id', 'unknown'),
                'content_type': head_response.get('ContentType', 'unknown') if 'head_response' in locals() else 'unknown'
            })
        
        # Sort by last modified date (newest first)
        logos.sort(key=lambda x: x['last_modified'], reverse=True)
        
        return logos
        
    except Exception as e:
        logger.error(f"Failed to list logos: {e}")
        return []


def delete_company_logo(s3_key: str) -> bool:
    """
    Delete a company logo from S3
    
    Args:
        s3_key: S3 object key
        
    Returns:
        True if successful, False otherwise
    """
    try:
        s3_manager = S3Manager()
        return s3_manager.delete_pdf(s3_key)  # Reuse delete method
    except Exception as e:
        logger.error(f"Failed to delete logo: {e}")
        return False


# ==================== SINGLETON INSTANCE ====================

_s3_manager = None

def get_s3_manager() -> S3Manager:
    """Get or create S3Manager singleton"""
    global _s3_manager
    if _s3_manager is None:
        _s3_manager = S3Manager()
    return _s3_manager


# ==================== UTILITY FUNCTIONS ====================

def validate_s3_connection() -> bool:
    """
    Validate S3 connection is working
    
    Returns:
        True if connection is valid, False otherwise
    """
    try:
        manager = get_s3_manager()
        manager._test_connection()
        return True
    except Exception as e:
        logger.error(f"S3 connection validation failed: {e}")
        return False


def get_s3_stats(prefix: str = "company-logo/") -> Dict[str, Any]:
    """
    Get statistics about S3 usage
    
    Args:
        prefix: S3 prefix to analyze
        
    Returns:
        Dictionary with stats
    """
    try:
        manager = get_s3_manager()
        
        response = manager.s3_client.list_objects_v2(
            Bucket=manager.bucket_name,
            Prefix=prefix
        )
        
        if 'Contents' not in response:
            return {
                'total_files': 0,
                'total_size': 0,
                'avg_size': 0
            }
        
        total_files = len(response['Contents'])
        total_size = sum(obj['Size'] for obj in response['Contents'])
        avg_size = total_size / total_files if total_files > 0 else 0
        
        return {
            'total_files': total_files,
            'total_size': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'avg_size': round(avg_size, 0),
            'avg_size_kb': round(avg_size / 1024, 2)
        }
        
    except Exception as e:
        logger.error(f"Failed to get S3 stats: {e}")
        return {
            'error': str(e)
        }
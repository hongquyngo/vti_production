# utils/s3_utils.py
"""
S3 Utilities for file upload/download
Handles PDF storage and retrieval from AWS S3
"""

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os
from io import BytesIO
from .config import AWS_CONFIG

logger = logging.getLogger(__name__)


class S3Manager:
    """Manager for S3 operations"""
    
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
        Upload PDF to S3
        
        Args:
            pdf_bytes: PDF file content as bytes
            filename: Name of the file
            metadata: Optional metadata to attach
            folder: S3 folder path
            
        Returns:
            Dictionary with upload details including URL
        """
        try:
            # Create full S3 key
            date_folder = datetime.now().strftime('%Y/%m/%d')
            s3_key = f"{self.app_prefix}/{folder}/{date_folder}/{filename}"
            
            # Prepare metadata
            upload_metadata = {
                'upload_timestamp': datetime.now().isoformat(),
                'content_type': 'application/pdf',
                'app': 'production_module'
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
            logger.error(f"Failed to upload PDF: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
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
        Download PDF from S3
        
        Args:
            s3_key: S3 object key
            
        Returns:
            PDF content as bytes or None if failed
        """
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            pdf_bytes = response['Body'].read()
            logger.info(f"✅ Downloaded PDF from S3: {s3_key}")
            
            return pdf_bytes
            
        except ClientError as e:
            logger.error(f"Failed to download PDF: {e}")
            return None
    
    def list_pdfs(self, prefix: str = None, max_items: int = 100) -> list:
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


# ==================== NEW FUNCTIONS FOR PDF GENERATOR ====================

def get_company_logo_from_s3(company_id: int, logo_path: str) -> Optional[bytes]:
    """
    Download company logo from S3
    
    Args:
        company_id: Company ID (for logging)
        logo_path: Path to logo in S3 (e.g., "company-logo/173613389453-logo.png")
        
    Returns:
        Logo bytes or None if not found
    """
    try:
        logger.info(f"Fetching logo for company {company_id}: {logo_path}")
        
        # Initialize S3 client
        s3_manager = S3Manager()
        
        # Download logo from S3
        # The logo_path already contains the full path like "company-logo/173613389453-logo.png"
        response = s3_manager.s3_client.get_object(
            Bucket=s3_manager.bucket_name,
            Key=logo_path
        )
        
        logo_bytes = response['Body'].read()
        logger.info(f"✅ Successfully downloaded logo: {logo_path} ({len(logo_bytes)} bytes)")
        
        return logo_bytes
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey':
            logger.warning(f"Logo not found in S3: {logo_path}")
        else:
            logger.error(f"Error downloading logo from S3: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading logo: {e}")
        return None


def upload_company_logo_to_s3(company_id: int, logo_bytes: bytes, 
                              filename: str = None) -> Optional[str]:
    """
    Upload company logo to S3
    
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
            filename = f"{company_id}_{timestamp}_logo.png"
        
        # Ensure filename has proper extension
        if not any(filename.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.svg']):
            filename += '.png'
        
        # Create S3 key
        s3_key = f"company-logo/{filename}"
        
        logger.info(f"Uploading logo for company {company_id}: {s3_key}")
        
        # Initialize S3 client
        s3_manager = S3Manager()
        
        # Determine content type
        content_type = 'image/png'
        if filename.endswith('.jpg') or filename.endswith('.jpeg'):
            content_type = 'image/jpeg'
        elif filename.endswith('.svg'):
            content_type = 'image/svg+xml'
        
        # Upload to S3
        s3_manager.s3_client.put_object(
            Bucket=s3_manager.bucket_name,
            Key=s3_key,
            Body=logo_bytes,
            ContentType=content_type,
            Metadata={
                'company_id': str(company_id),
                'upload_timestamp': datetime.now().isoformat()
            }
        )
        
        logger.info(f"✅ Logo uploaded successfully: {s3_key}")
        return s3_key
        
    except Exception as e:
        logger.error(f"Failed to upload logo: {e}")
        return None


def list_company_logos(company_id: Optional[int] = None) -> list:
    """
    List all company logos in S3
    
    Args:
        company_id: Optional filter by company ID
        
    Returns:
        List of logo objects
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
            
            logos.append({
                'key': obj['Key'],
                'filename': os.path.basename(obj['Key']),
                'size': obj['Size'],
                'last_modified': obj['LastModified'].isoformat(),
            })
        
        return logos
        
    except Exception as e:
        logger.error(f"Failed to list logos: {e}")
        return []


# Create global instance for backward compatibility
_s3_manager = None

def get_s3_manager() -> S3Manager:
    """Get or create S3Manager singleton"""
    global _s3_manager
    if _s3_manager is None:
        _s3_manager = S3Manager()
    return _s3_manager
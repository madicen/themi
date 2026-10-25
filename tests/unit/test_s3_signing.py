"""The SigV4 signer against AWS's published example (IAM ListUsers, 2015-08-30)."""

from themi.backup.s3 import sign, signing_key

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"


def test_the_signing_key_matches_aws() -> None:
    key = signing_key(SECRET, "20150830", "us-east-1", "iam")
    assert key.hex() == "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9"


def test_the_signature_matches_aws() -> None:
    payload = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    header = sign(
        "GET",
        "https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08",
        {
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Host": "iam.amazonaws.com",
            "X-Amz-Date": "20150830T123600Z",
        },
        payload,
        access_key="AKIDEXAMPLE",
        secret=SECRET,
        region="us-east-1",
        service="iam",
        amz_date="20150830T123600Z",
    )
    assert header == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/iam/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date, "
        "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"
    )

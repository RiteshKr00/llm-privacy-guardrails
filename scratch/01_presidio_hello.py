from presidio_analyzer import AnalyzerEngine

sample_text="""On March 14, 2026, a new customer profile was created for Aarav Verhoeff during a routine software testing exercise. According to the sample record, Aarav requested that all correspondence be sent to aarav.verhoeff@example.com. The profile was intentionally populated with fictional information to validate data-processing workflows and should not be treated as real customer data.
The test account also included a placeholder contact number, +1-202-555-0123, which is reserved for demonstration purposes. During the quality assurance review, team members verified that the system could correctly detect and mask phone numbers appearing in both structured and unstructured text. Several automated alerts were triggered as expected, confirming that the detection pipeline was functioning correctly.
For address validation testing, the account listed a residence at 1234 Fictional Maple Street, Springfield, ZZ 99999. The address was designed to be obviously fake while still resembling a realistic mailing location. This allowed engineers to confirm that address parsing, geocoding safeguards, and privacy filters behaved consistently across multiple environments
Finally, a sample payment method was attached to the record using the well-known test card number 4111-1111-1111-1111. The card was never used for real transactions and existed solely to verify formatting checks, tokenization workflows, and redaction logic. After all tests were completed, the fictional customer profile for Aarav Verhoeff was archived and retained only as synthetic data for future system validation exercises."""


# print(sample_text)

analyzer=AnalyzerEngine()
results = analyzer.analyze(text=sample_text, language='en')

print(results)
for r in results:
    matched = sample_text[r.start:r.end]
    # print("------------>>",r)
    print(f"{r.entity_type:<15} '{matched}'  score={r.score:.2f}  offsets=({r.start}, {r.end})")

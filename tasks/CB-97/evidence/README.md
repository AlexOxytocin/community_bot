# CB-97 visual evidence

`authenticated/` содержит settled production screenshots, полученные через
authenticated bootstrap и mocked existing API contract. Для каждого ID есть
пара `375x812` и `430x932`. Скрипт воспроизведения:

```powershell
.\.venv\Scripts\python.exe tasks/CB-97/capture_connected_evidence.py
```

Presentation harness и direct `navigatePresentationScreen` не используются.

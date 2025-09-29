# import speech_recognition as sr
# from google.cloud.speech_v1.types.cloud_speech import RecognizeResponse

# from helpers import decorators
# from helpers.audio import Audio


# class Recognizer:
#     _recognizer = sr.Recognizer()

#     @decorators.exit_on_exception
#     @staticmethod
#     def recognize_speech_from_mic() -> RecognizeResponse | str:
#         audio = Audio.record_audio()
#         response = Recognizer._recognizer.recognize_google_cloud(audio)  # type: ignore

#         return response

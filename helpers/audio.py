import os

import playsound
import pyttsx3

# import speech_recognition as sr


class TTS_Engine:
    def __init__(self) -> None:
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", 150)
        self._engine.setProperty("volume", 0.6)
        self.__voices = self._engine.getProperty("voices")  # id=0: EN, id=1: PL
        self._engine.setProperty("voice", self.__voices[1].id)

    def text_to_speech(self, text: str) -> None:
        self._engine.say(text)
        self._engine.runAndWait()

    def save_text_to_file(self, text: str, filename: str) -> None:
        self._engine.save_to_file(text, filename)
        self._engine.runAndWait()


class Audio:
    # _microphone = sr.Microphone()
    # _recognizer = sr.Recognizer()

    @staticmethod
    def play_audio_from_file(filename: str) -> None:
        if os.path.exists(filename):
            playsound.playsound(filename, block=False)
        else:
            print(f"Audio file {filename} does not exist.")

    @staticmethod
    def save_text_to_file(text: str, filename: str) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        tts_engine = TTS_Engine()

        tts_engine.save_text_to_file(text, filename)

        del tts_engine

    @staticmethod
    def text_to_speech(text: str) -> None:
        tts_engine = TTS_Engine()

        tts_engine.text_to_speech(text)

        del tts_engine

    # @staticmethod
    # def record_audio(duration: int = 3) -> sr.AudioData:
    #     Audio.play_audio_from_file("voice/bot/listening.wav")

    #     with Audio._microphone as source:  # type: ignore
    #         audio = Audio._recognizer.record(source, duration=duration)

    #         return audio
    #         return audio

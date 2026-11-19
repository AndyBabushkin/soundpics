"""Выделение значимых слов из распознанного текста и формирование запросов.

Логика: из текста убираем служебные слова (стоп-слова RU/EN), накапливаем
содержательные; как только набралось `trigger` слов — формируем запрос из
не более чем `max_per_query` слов (по умолчанию 2-3, как в ТЗ).
"""
from __future__ import annotations

import re
from collections import deque

WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")

RU_STOP = {
    # предлоги, союзы, частицы
    "и", "в", "во", "на", "с", "со", "по", "за", "из", "от", "до", "у", "о", "об",
    "при", "про", "для", "что", "чтобы", "как", "когда", "где", "куда", "откуда",
    "почему", "зачем", "сколько", "какой", "какая", "какое", "какие", "каков",
    "который", "которая", "которые", "которого", "которой", "которых",
    "этот", "эта", "это", "эти", "этого", "этой", "этих", "тот", "та", "те",
    "того", "той", "ту", "там", "тут", "здесь", "сейчас", "потом", "тогда",
    "уже", "еще", "очень", "тоже", "также", "только", "даже", "именно", "просто",
    "почти", "совсем", "не", "ни", "нет", "да", "бы", "ли", "же", "вот", "вон",
    "ну", "ах", "ох", "эх", "ой", "ура", "везде", "всегда", "никогда", "иногда",
    "снова", "опять", "все", "или", "но", "а", "давай", "давайте", "пусть",
    "пускай", "надо", "нужно", "можно", "нельзя", "ладно", "хорошо", "спасибо",
    "пожалуйста", "смотри", "слушай", "знаешь", "понимаешь", "ой",
    # местоимения
    "я", "ты", "он", "она", "оно", "мы", "вы", "они", "меня", "тебя", "его",
    "ее", "их", "нас", "вас", "себе", "мой", "твой", "наш", "ваш", "свой",
    "своя", "свое", "свои", "моя", "мое", "мои", "твоя", "твое", "твои",
    "наша", "наше", "наши", "ваша", "ваше", "ваши", "кто", "кого", "кому",
    "кем", "чем",
    # числительные и порядковые
    "один", "одна", "одно", "одни", "два", "две", "три", "четыре", "пять",
    "шесть", "семь", "восемь", "девять", "десять", "сто", "тысяча", "миллион",
    "первый", "второй", "третий",
    # вспомогательные глаголы
    "быть", "есть", "был", "была", "было", "были", "будет", "буду", "будешь",
    "будете", "будем", "будьте", "мочь", "могу", "можешь", "может", "можем",
    "можете", "могут", "мог", "могла", "могли", "хотеть", "хочу", "хочешь",
    "хочет", "хотим", "хотите", "хотят", "стать", "стал", "стала", "стали",
}

EN_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
    "where", "why", "how", "what", "which", "who", "whom", "whose", "that",
    "this", "these", "those", "there", "here", "is", "am", "are", "was",
    "were", "be", "been", "being", "do", "does", "did", "doing", "have",
    "has", "had", "having", "will", "would", "shall", "should", "can",
    "could", "may", "might", "must", "ought", "i", "you", "he", "she",
    "it", "we", "they", "me", "him", "her", "us", "them", "my", "your",
    "his", "its", "our", "their", "mine", "yours", "hers", "ours", "theirs",
    "myself", "yourself", "himself", "herself", "itself", "ourselves",
    "themselves", "of", "in", "on", "at", "to", "for", "from", "by", "with",
    "about", "into", "over", "under", "again", "further", "once", "just",
    "now", "also", "too", "very", "so", "such", "no", "not", "nor", "only",
    "own", "same", "than", "as", "up", "down", "out", "off", "above", "below",
    "between", "during", "before", "after", "through", "while", "because",
    "until", "both", "each", "few", "more", "most", "other", "some", "any",
    "all", "yeah", "hey", "oh", "well", "like", "get", "got", "go", "going",
    "really", "know", "think", "see", "want", "let", "make", "take", "come",
    "one", "two", "three", "four", "five", "first", "second", "back", "way",
}

STOP_WORDS = RU_STOP | EN_STOP


class KeywordExtractor:
    """Накапливает значимые слова и выдаёт поисковые запросы по 2-3 слова."""

    def __init__(self, trigger: int = 2, max_per_query: int = 3, max_pending: int = 12):
        self.trigger = max(1, int(trigger))
        self.max_per_query = max(1, int(max_per_query))
        self.max_pending = max(self.trigger, int(max_pending))
        self.pending: list[str] = []
        self.recent: deque[str] = deque(maxlen=30)

    def feed(self, text: str, allow_emit: bool = True) -> list[str]:
        """Обрабатывает кусок распознанного текста; возвращает готовые запросы.

        allow_emit=False — копить слова, но не формировать запросы
        (используется, когда еще не прошла пауза min_interval между картинками).
        """
        for word in WORD_RE.findall(text.lower()):
            word = word.replace("ё", "е")
            if len(word) < 2 or word in STOP_WORDS:
                continue
            self.pending.append(word)

        queries: list[str] = []
        if not allow_emit:
            if len(self.pending) > self.max_pending:
                del self.pending[: len(self.pending) - self.max_pending]
            return queries

        while len(self.pending) >= self.trigger:
            take = self.pending[: self.max_per_query]
            del self.pending[: len(take)]
            query = " ".join(take)
            if query in self.recent:  # не показываем один и тот же запрос дважды
                continue
            self.recent.append(query)
            queries.append(query)
        return queries

"""UTF-8 byte-level wrapping

Convenient utility for text wrapping on byte boundnaries.
"""

__all__ = ['Utf8Wrapper']


class Utf8Wrapper:
    def __init__(self, **kwargs):
        self.width = kwargs.get('width', 100)

    def _split_words(self, text):
        while text:
            word = []
            seen_non_space = False
            for byte in text:
                if byte != 0x20:
                    seen_non_space = True
                elif seen_non_space and byte == 0x20:
                    break

                word.append(byte)

            if seen_non_space:
                yield word
            text[:len(word)] = []

    def _split_chars(self, word):
        while word:
            chars = [word.pop(0)]
            for char in word:
                if 0x80 <= char < 0xC0:
                    chars.append(char)
                else:
                    break

            yield(chars)
            word[:len(chars)-1] = []


    def _lay_long_word(self, word):
        chars = list(self._split_chars(word))
        line = []
        while chars:
            char = chars.pop(0)
            if len(char) < self.width - len(line):
                line.extend(char)
            else:
                yield line
                line = char

        if line:
            yield line

    def _lay_lines(self, words):
        line = []
        while words:
            word = words.pop(0)
            if len(word) < self.width - len(line):
                line.extend(word)
            elif not line:
                for line in self._lay_long_word(word):
                    yield bytes(line).decode('UTF-8')
                line = []
            else:
                yield bytes(line).decode('UTF-8')
                line = word

        if line:
            yield bytes(line).decode('UTF-8')

    def wrap(self, text):
        text = text.encode('UTF-8')

        text = list(text)
        words = list(self._split_words(text))

        return list(self._lay_lines(words))

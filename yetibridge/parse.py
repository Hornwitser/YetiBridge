# parse.py - Simple split of quoted sequences
#
# Splits a string of optionally quoted arguments into a list of words,
# using a 3 stage process.
#
# 1. Takes characters escaped with '\' and turns them into literals.
# 2. Takes quoted sequences and turns them into literals.
# 3. Splits words on whitespace.

class Literal:
    def __init__(self, characters):
        self.characters = ''
        for char in characters:
            if isinstance(char, Literal):
                self.characters += char.characters
            else:
                self.characters += char

def split(string):
    # Turn into a list of characters
    array = list(map(str, string))

    # Turn escaped characters into character literals
    escaped = []
    while array:
        item = array.pop(0)
        if item == '\\' and array:
            escaped.append(Literal(array.pop(0)))
        else:
            escaped.append(item)

    # Turn quoted string into word literals.
    quoted = []
    while escaped:
        item = escaped.pop(0)
        if item == '"':
            word = []
            while escaped:
                item = escaped.pop(0)
                if item =='"':
                    quoted.append(Literal(word))
                    break
                else:
                    word.append(item)
            else:
                raise ValueError("unmatched quote")
        else:
            quoted.append(item)

    # Join adjacent sequences of literals and characters not
    # separated by blanks.
    split = []
    word = []
    while quoted:
        item = quoted.pop(0)
        if item != " " and item != "\t":
            word.append(item)
        elif word:
            split.append(Literal(word))
            word.clear()
    if word:
        split.append(Literal(word))

    # Turn the sequence of literals into a list of strings
    return list(map(lambda l: l.characters, split))

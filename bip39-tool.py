def load_bip39_wordlist():
    with open("bip39_wordlist.txt", "r") as file:
        wordlist = file.read().splitlines()
    return wordlist

def find_bip39_numbers(words):
    wordlist = load_bip39_wordlist()
    word_number_pairs = []
    for word in words:
        if word in wordlist:
            number = wordlist.index(word)
            word_number_pairs.append((word, number))
        else:
            word_number_pairs.append((word, "Word not found in BIP39 list"))
    return word_number_pairs

def calculate_binary_representation(number):
    binary_rep = bin(number)[2:].zfill(11)
    return [int(bit) for bit in binary_rep]

def generate_matrix(words):
    matrix = [[0] * 11 for _ in range(len(words))]
    word_number_pairs = find_bip39_numbers(words)
    for i, (_, number) in enumerate(word_number_pairs):
        binary_rep = calculate_binary_representation(number)
        for j in range(11):
            matrix[i][j] = binary_rep[j]
    return matrix

def convert_to_emoji(value):
    if value == 1:
        return "✅"  # OK emoji
    else:
        return "❌"   # Space

def main():
    user_input = input("Enter your BIP39 24 or 12 words (separated by spaces): ")
    words = user_input.strip().split()
    position = 0
    word_number_pairs = find_bip39_numbers(words)
    for word, number in word_number_pairs:
        position = position + 1
        print(f"{str(position).zfill(2)} - {word} - {number}")

    matrix = generate_matrix(words)
    
    print("Matrix Representation:")
    line = 0
    for row in matrix:
        line = line + 1
        emoji_row = [convert_to_emoji(bit) for bit in row]
        print(f"{str(line).zfill(2)} - {''.join(emoji_row)}")

if __name__ == "__main__":
    main()



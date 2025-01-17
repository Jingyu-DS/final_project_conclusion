import requests
import zipfile
import os
import collections
import torch
from torch.utils.data import DataLoader, TensorDataset
from torch.optim.lr_scheduler import StepLR
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

from google.colab import drive
drive.mount('/content/drive')

# Utlities
import os
import requests
import zipfile

class DataHandler:
  def _download(self):
    # File information
    file_name = '/content/drive/MyDrive/SDS631_FINAL/deu-eng.zip'
    extracted_dir = "deu-eng-data"
    with zipfile.ZipFile(file_name, 'r') as zip_ref:
      zip_ref.extractall(extracted_dir)

    print("Extracted files:", os.listdir(extracted_dir))

    with open(os.path.join(extracted_dir, "deu.txt"), encoding="utf-8") as f:
      data = f.readlines()

    count = 0
    cleaned_data = []
    for line in data:
      parts = line.split('\t')
      if len(parts) >= 2:
        source = parts[0].strip()
        target = parts[1].strip()
      count += 1
      if count % 20 == 0:
        cleaned_data.append((source, target))

    for source, target in cleaned_data[:5]:
      print(f"{source} -> {target}")

    return cleaned_data

  def _preprocess(self, text):
    text = text.replace('\u202f', ' ').replace('\xa0', ' ')
    no_space = lambda char, prev_char: char in ',.!?' and prev_char != ' '
    out = [' ' + char if i > 0 and no_space(char, text[i - 1]) else char for i, char in enumerate(text.lower())]
    return ''.join(out)

  def _tokenize(self, text):
    src, tgt = [], []
    for i, line in enumerate(text.split('\n')):
      parts = line.split('\t')
      if len(parts) == 2:
        src.append([t for t in f'{parts[0]} <eos>'.split(' ') if t])
        tgt.append([t for t in f'{parts[1]} <eos>'.split(' ') if t])
    return src, tgt

  def preprocess_and_tokenize(self, data):
    processed_data = '\n'.join([f'{self._preprocess(src)}\t{self._preprocess(tgt)}'
                                    for src, tgt in data])

    return self._tokenize(processed_data)

# Test the data and proprocessing
data_handler = DataHandler()
cleaned_data = data_handler._download()
src, tgt = data_handler.preprocess_and_tokenize(cleaned_data)
print(src[:6], tgt[:6])

# Building Vocab for target and source
class Vocab:
    """Vocabulary for text."""
    def __init__(self, tokens=[], min_freq=0, reserved_tokens=[]):
        """Defined in :numref:`sec_text-sequence`"""
        # Flatten a 2D list if needed
        if tokens and isinstance(tokens[0], list):
            tokens = [token for line in tokens for token in line]
        # Count token frequencies
        counter = collections.Counter(tokens)
        self.token_freqs = sorted(counter.items(), key=lambda x: x[1],
                                  reverse=True)
        # The list of unique tokens
        self.idx_to_token = list(sorted(set(['<unk>'] + reserved_tokens + [
            token for token, freq in self.token_freqs if freq >= min_freq])))
        self.token_to_idx = {token: idx
                             for idx, token in enumerate(self.idx_to_token)}

    def __len__(self):
        return len(self.idx_to_token)

    def __getitem__(self, tokens):
        if not isinstance(tokens, (list, tuple)):
            return self.token_to_idx.get(tokens, self.unk)
        return [self.__getitem__(token) for token in tokens]

    def to_tokens(self, indices):
        if hasattr(indices, '__len__') and len(indices) > 1:
            return [self.idx_to_token[int(index)] for index in indices]
        return self.idx_to_token[indices]

    @property
    def unk(self):  # Index for the unknown token
        return self.token_to_idx['<unk>']

def build_array(sentences, vocab=None, num_steps=9, is_tgt=False):
    def pad_or_trim(seq, t):
        return seq[:t] if len(seq) > t else seq + ['<pad>'] * (t - len(seq))

    sentences = [pad_or_trim(s, num_steps) for s in sentences]

    if is_tgt:
        sentences = [['<bos>'] + s for s in sentences]

    if vocab is None:
        vocab = Vocab(sentences, min_freq=2)

    array = torch.tensor([vocab[s] for s in sentences])

    valid_len = (array != vocab['<pad>']).type(torch.int32).sum(1)

    return array, vocab, valid_len

def build_arrays(src_sentences, tgt_sentences, src_vocab=None, tgt_vocab=None, num_steps=9):
    src_array, src_vocab, src_valid_len = build_array(src_sentences, vocab=src_vocab, num_steps=num_steps, is_tgt=False)
    tgt_array, tgt_vocab, _ = build_array(tgt_sentences, vocab=tgt_vocab, num_steps=num_steps, is_tgt=True)

    tgt_input = tgt_array[:, :-1]
    tgt_output = tgt_array[:, 1:]

    return (src_array, tgt_input, src_valid_len, tgt_output, src_vocab, tgt_vocab)

# test the functions
result = build_arrays(src, tgt, num_steps=5)

src_array, tgt_input, src_valid_len, tgt_output, src_vocab, tgt_vocab = result

print("Source Array:\n", src_array)
print("Target Input:\n", tgt_input)
print("Source Valid Length:\n", src_valid_len)
print("Target Output:\n", tgt_output)

def train_dataloader(src_array, tgt_input, src_valid_len, tgt_output, batch_size):
    dataset = TensorDataset(src_array, tgt_input, src_valid_len, tgt_output)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    return dataloader

batch_size = 3
dataloader = train_dataloader(src_array, tgt_input, src_valid_len, tgt_output, batch_size)
src_sample, tgt_sample, src_valid_len, label = next(iter(dataloader))
print('source:', src_sample.type(torch.int32))
print('decoder input:', tgt_sample.type(torch.int32))
print('source len excluding pad:', src_valid_len.type(torch.int32))
print('label:', label.type(torch.int32))

class Encoder(nn.Module):
    def __init__(self, input_dim, embed_dim, hidden_dim, num_layers=1):
        super(Encoder, self).__init__()
        self.embedding = nn.Embedding(input_dim, embed_dim)
        self.gru = nn.GRU(embed_dim, hidden_dim, num_layers, batch_first=True)

    def forward(self, src, src_len):
        # src: (batch_size, src_len)
        embedded = self.embedding(src)  # (batch_size, src_len, embed_dim)
        packed_embedded = nn.utils.rnn.pack_padded_sequence(embedded, src_len.cpu(), batch_first=True, enforce_sorted=False)
        packed_outputs, hidden = self.gru(packed_embedded)  # hidden: (num_layers, batch_size, hidden_dim)
        return hidden

class Decoder(nn.Module):
    def __init__(self, output_dim, embed_dim, hidden_dim, num_layers=1):
        super(Decoder, self).__init__()
        self.embedding = nn.Embedding(output_dim, embed_dim)
        self.gru = nn.GRU(embed_dim, hidden_dim, num_layers, batch_first=True)
        self.fc_out = nn.Linear(hidden_dim, output_dim)

    def forward(self, input, hidden):
        # input: (batch_size) -> single token
        # hidden: (num_layers, batch_size, hidden_dim)
        input = input.unsqueeze(1)  # (batch_size, 1)
        embedded = self.embedding(input)  # (batch_size, 1, embed_dim)
        output, hidden = self.gru(embedded, hidden)  # output: (batch_size, 1, hidden_dim)
        prediction = self.fc_out(output.squeeze(1))  # (batch_size, output_dim)
        return prediction, hidden

class Seq2Seq(nn.Module):
    def __init__(self, encoder, decoder, device):
        super(Seq2Seq, self).__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.device = device

    def forward(self, src, src_len, tgt, teacher_forcing_ratio=0.5):
        # src: (batch_size, src_len)
        # tgt: (batch_size, tgt_len)
        batch_size = src.shape[0]
        tgt_len = tgt.shape[1]
        tgt_vocab_size = self.decoder.fc_out.out_features

        outputs = torch.zeros(batch_size, tgt_len, tgt_vocab_size).to(self.device)

        hidden = self.encoder(src, src_len)
        input = tgt[:, 0]  # First input to the decoder is the <bos> token

        for t in range(1, tgt_len):
            output, hidden = self.decoder(input, hidden)
            outputs[:, t, :] = output
            top1 = output.argmax(1)  # Greedy decoding
            input = tgt[:, t] if torch.rand(1).item() < teacher_forcing_ratio else top1

        return outputs

def train(model, dataloader, optimizer, criterion, device):
    model.train()
    epoch_loss = 0
    STEPS = 0
    for src, tgt, src_len, tgt_out in dataloader:
        src, tgt, src_len, tgt_out = src.to(device), tgt.to(device), src_len.to(device), tgt_out.to(device)

        optimizer.zero_grad()
        output = model(src, src_len, tgt)
        output_dim = output.shape[-1]

        # Reshape outputs and targets for loss calculation
        output = output[:, 1:].reshape(-1, output_dim)
        tgt_out = tgt_out[:, 1:].reshape(-1)

        loss = criterion(output, tgt_out)
        loss.backward()
        optimizer.step()
        epoch_loss += loss.item()
        STEPS += 1
        if STEPS % 2000 == 0:
          print(f"Eopch is still running successfully, for intermediate progress check, current loss: {loss.item():.4f}")

    return epoch_loss / len(dataloader)

INPUT_DIM = len(src_vocab)
OUTPUT_DIM = len(tgt_vocab)
print(INPUT_DIM, OUTPUT_DIM)
EMBED_DIM = 256
HIDDEN_DIM = 256
NUM_LAYERS = 2
BATCH_SIZE = 256
NUM_EPOCHS = 10
LEARNING_RATE = 0.005
TEACHER_FORCING_RATIO = 0.5
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
PAD_INDEX = tgt_vocab['<pad>']

# Instantiate the model
encoder = Encoder(INPUT_DIM, EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
decoder = Decoder(OUTPUT_DIM, EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
model = Seq2Seq(encoder, decoder, DEVICE).to(DEVICE)

# Optimizer and Loss Function
optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
scheduler = StepLR(optimizer, step_size=3, gamma=0.1)
criterion = nn.CrossEntropyLoss(ignore_index=PAD_INDEX)

# Example usage with a DataLoader
# Replace 'train_dataloader' with your own DataLoader implementation
for epoch in range(NUM_EPOCHS):
    train_loss = train(model, dataloader, optimizer, criterion, DEVICE)
    scheduler.step()
    print(f"Epoch {epoch+1}/{NUM_EPOCHS}, Loss: {train_loss:.4f}")

current_lr = optimizer.param_groups[0]['lr']
print(f"Final learning rate: {current_lr}")


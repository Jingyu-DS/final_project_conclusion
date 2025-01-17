import tensorflow_datasets as tfds
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

dataset, info = tfds.load("smallnorb", with_info=True, as_supervised=False)
train_tfds = dataset['train']
test_tfds = dataset['test']

num_classes = info.features['label_category'].num_classes

class SmallNORBDataset(Dataset):
    def __init__(self, tfds_dataset):
        self.data = list(tfds_dataset)
    def __len__(self):
        return len(self.data)
    def __getitem__(self, idx):
        example = self.data[idx]
        img = example['image'].numpy() # shape (96,96,1)
        label = example['label_category'].numpy()

        img = torch.tensor(img, dtype=torch.float32)/255.0
        img = img.permute(2,0,1)  # (1,96,96)
        return img, label

train_dataset = SmallNORBDataset(train_tfds)
test_dataset = SmallNORBDataset(test_tfds)

train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=64)

class MyModel(nn.Module):
    def __init__(self, num_classes=5):
        super(MyModel, self).__init__()
        self.fc = nn.Linear(96*96, num_classes)
    def forward(self, x):
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x

model = MyModel(num_classes=num_classes)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=1e-3)

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)

steps = 0
avg_params = {name: p.detach().clone() for name, p in model.named_parameters()}

# Proximal parameter (L1 regularization coefficient)
l1_lambda = 1e-4

def prox_l1(param, alpha):
    # Soft-thresholding operator
    return torch.sign(param) * torch.clamp(param.abs() - alpha, min=0.0)

n_epochs = 100
for epoch in range(n_epochs):
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for X_batch, y_batch in train_loader:
        X_batch, y_batch = X_batch.to(device), y_batch.to(device)

        optimizer.zero_grad()
        outputs = model(X_batch)
        loss = criterion(outputs, y_batch)
        loss.backward()
        optimizer.step()

        running_loss += loss.item()
        _, predicted = torch.max(outputs, 1)
        correct += (predicted == y_batch).sum().item()
        total += y_batch.size(0)

        # Update Polyak average
        steps += 1
        with torch.no_grad():
            for name, p in model.named_parameters():
                # Update averaged params
                avg_params[name] = avg_params[name] + (p - avg_params[name]) / steps

            # Apply proximal operator (L1 in this example) to the averaged parameters
            for name in avg_params:
                avg_params[name] = prox_l1(avg_params[name], l1_lambda)

    train_loss = running_loss / len(train_loader)
    train_acc = correct / total
    print(f"Epoch [{epoch+1}/{n_epochs}] - Loss: {train_loss:.4f}, Accuracy: {train_acc:.4f}")

prox_model = MyModel(num_classes=num_classes).to(device)
with torch.no_grad():
    for name, p in prox_model.named_parameters():
        p.copy_(avg_params[name])

# Evaluate
prox_model.eval()
correct = 0
total = 0
with torch.no_grad():
    for X_batch, y_batch in test_loader:
        X_batch, y_batch = X_batch.to(device), y_batch.to(device)
        outputs = prox_model(X_batch)
        _, predicted = torch.max(outputs, 1)
        correct += (predicted == y_batch).sum().item()
        total += y_batch.size(0)

test_acc = correct / total
print(f"Proximal Averaged Model Test Accuracy: {test_acc:.4f}")

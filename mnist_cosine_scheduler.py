import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import CosineAnnealingLR
import matplotlib.pyplot as plt

batch_size = 64
lr = 0.1
num_epochs = 5
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,)) # Normalization for MNIST
])

train_dataset = datasets.MNIST(root="./data", train=True, download=True, transform=transform)
test_dataset = datasets.MNIST(root="./data", train=False, download=True, transform=transform)

train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=2)
test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=2)

class SimpleNet(nn.Module):
    def __init__(self):
        super(SimpleNet, self).__init__()
        self.fc1 = nn.Linear(28*28, 256)
        self.fc2 = nn.Linear(256, 10)

    def forward(self, x):
        x = x.view(-1, 28*28)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x

model = SimpleNet().to(device)

optimizer = optim.SGD(model.parameters(), lr=0.1, momentum=0.9)
# use a CosineAnnealingLR that decreases the LR from the initial value to 0 over T_max epochs.
scheduler = CosineAnnealingLR(optimizer, T_max=num_epochs, eta_min=0.001)

num_epochs = 5
train_losses = []
test_losses = []

def train(epoch):
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for batch_idx, (data, targets) in enumerate(train_loader):
        data, targets = data.to(device), targets.to(device)
        optimizer.zero_grad()
        outputs = model(data)
        loss = F.cross_entropy(outputs, targets)
        loss.backward()
        optimizer.step()

        running_loss += loss.item() * data.size(0)
        _, predicted = outputs.max(1)
        total += targets.size(0)
        correct += predicted.eq(targets).sum().item()

    epoch_loss = running_loss / total
    epoch_acc = 100. * correct / total
    print(f"Train Epoch: {epoch} | Loss: {epoch_loss:.4f} | Accuracy: {epoch_acc:.2f}%")
    return epoch_loss

def test():
    model.eval()
    test_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for data, targets in test_loader:
            data, targets = data.to(device), targets.to(device)
            outputs = model(data)
            loss = F.cross_entropy(outputs, targets)
            test_loss += loss.item() * data.size(0)
            _, predicted = outputs.max(1)
            total += targets.size(0)
            correct += predicted.eq(targets).sum().item()

    test_loss = test_loss / total
    accuracy = 100. * correct / total
    return test_loss, accuracy

for epoch in range(1, num_epochs+1):
    train(epoch)
    test_loss, test_acc = test()
    print(f"Test  Epoch: {epoch} | Loss: {test_loss:.4f} | Accuracy: {test_acc:.2f}%")

    # Step the scheduler after each epoch
    scheduler.step()

# After training completes, the learning rate will have followed the cosine schedule.
current_lr = optimizer.param_groups[0]['lr']
print(f"Final learning rate: {current_lr}")

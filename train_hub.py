import random
import deepspeed
import torch
from torch.utils.data import DataLoader
from tqdm.auto import trange
import torch.distributed as distributed

from gpt_neox import (GPTNeoX, AutoregressiveWrapper, GPT2Dataset, extract_tarfile,
                      prepare_optimizer_parameters, get_tokenizer, is_main)

from gpt_neox.utils import get_args, get_params
from gpt_neox.datasets import get_hub_dataset
# from gpt_neox.datasets import DynamicDataset

train_args = get_args()
params = get_params(train_args.model)

# tokenizer
tokenizer = get_tokenizer(tokenizer_type=params["tokenizer"].get("type", None),
                          from_pretrained=params["tokenizer"].get(
                              "from_pretrained", True),
                          add_padding_token=params["tokenizer"].get("add_padding_token", False))
vocab_size = len(
    tokenizer) if params["vocab_size"] is None else params["vocab_size"]

# instantiate GPT-like decoder model
params["seq_len"] = 1024
model = GPTNeoX(
    num_tokens=vocab_size,
    dim=params["hidden_dim"],
    seq_len=params["seq_len"],
    depth=params["n_layers"],
    heads=params["n_heads"],
    dim_head=params["dim_head"]
)

model = AutoregressiveWrapper(model)

# prepare data
dset_params = params["dataset"]
assert dset_params is not None

deepspeed.init_distributed(dist_backend='nccl')
# barrier will force processes to stop until *all* processes have reached the barrier
torch.distributed.barrier()
# if is_main(train_args):
#     prepare_data(dset_params["name"])
#     torch.distributed.barrier()  # barrier will force processes to stop until *all* processes have reached the barrier
# else:
#     torch.distributed.barrier()

train_dataset = get_hub_dataset()

# train_dataset = GPT2Dataset(glob_pattern=dset_params["train_path"],
#                             seq_len=params["seq_len"],
#                             train=True,
#                             **dset_params)

# eval_dataset = GPT2Dataset(glob_pattern=dset_params["eval_path"],
#                            seq_len=params["seq_len"],
#                            train=False,
#                            **dset_params)

# val_loader = DataLoader(eval_dataset, batch_size=params["eval_batch_size"])
# val_loader = iter(val_loader)

# optimizer
if train_args.local_rank == -1:  # non-deepspeed
    optim = torch.optim.Adam(model.parameters(), lr=params["learning_rate"])
else:
    optim = None  # deepspeed will prepare the optimizer for us


# training
ds_model_params = prepare_optimizer_parameters(model)

# deepspeed loader
model_engine, optim, train_loader, _ = deepspeed.initialize(args=train_args,
                                                            model=model,
                                                            optimizer=optim,
                                                            model_parameters=ds_model_params,
                                                            training_data=train_dataset)

print("OPTIMIZER: ", optim)
pbar = trange(params.get("train_steps", 1), mininterval=10.,
              desc='Training Model', dynamic_ncols=True)
for _ in pbar:
    for i, data in enumerate(train_loader):
        if i > params["train_steps"]:
            break
        model_engine.train()
        is_main = model_engine.local_rank == 0
#         data = torch.stack([d.to(model_engine.local_rank) for d in data])[:,:1024]
        data = data.to(model_engine.local_rank)

        loss = model_engine(data)
        model_engine.backward(loss)
        model_engine.step()

        pbar.set_description(f'Training Loss: {loss.item():.4f}')
        pbar.update()

#         if params.get("validate_every") is not None:
#             if is_main and i % params["validate_every"] == 0:
#                 model_engine.eval()
#                 with torch.no_grad():
#                     val_data = next(val_loader).cuda()
#                     loss = model_engine(val_data)
#                     pbar.write(f'Validation Loss: {loss.item()}')

#         if params.get("generate_every") is not None:
#             if is_main and i % params["generate_every"] == 0:
#                 model.eval()
#                 val_data = next(val_loader).cuda()
#                 inp = random.choice(val_data)[:-1]
#                 prime = tokenizer.decode(inp)
#                 pbar.write(f"{prime} \n\n {'*' * 100}")
#                 sample = model.generate(inp.cuda(), params["generate_length"])
#                 output_str = tokenizer.decode(sample)
#                 pbar.write(output_str)

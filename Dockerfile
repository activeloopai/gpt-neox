from deepspeed/deepspeed:torch150_cuda102

ADD ./ /workspace
WORKDIR /workspace

RUN pip install -r requirements.txt
RUN pip install --upgrade deepspeed
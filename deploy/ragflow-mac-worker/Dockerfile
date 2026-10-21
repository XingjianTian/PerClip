FROM infiniflow/ragflow@sha256:1281817d496e25d3d9fca55df8a6b195e056fd467a2030ec950bbb654df0f362

COPY worker.patch /tmp/perclip-worker.patch
RUN printf '%s\n' \
    'f4cba671227f7a1a12463daece5061db755fc83fa47d7d4b960f7872e2ee3cc2  rag/svr/task_executor.py' \
    '6a3b0ad895498d60dfce2470f47ad720699cc374837701f6865a5ee3c0058b30  api/db/services/task_service.py' \
    'ded801e5b88b1a98e56314e2bf83323fb61c350f653519070125160ff866dec0  rag/svr/task_executor_refactor/task_handler.py' \
    | sha256sum -c - \
    && patch --batch --fuzz=0 -p1 < /tmp/perclip-worker.patch \
    && python3 -m py_compile rag/svr/task_executor.py api/db/services/task_service.py rag/svr/task_executor_refactor/task_handler.py

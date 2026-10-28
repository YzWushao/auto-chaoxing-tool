"""Reproduce the CPU artifact from the pinned upstream ORT model, without training.

Copyright (c) 2026 YzWushao. SPDX-License-Identifier: AGPL-3.0-only
Uses ONNX Runtime's installed FlatBuffers schema reader (MIT).
"""
from hashlib import sha256
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from onnxruntime.tools.ort_format_model import ort_model_processor
from onnxruntime.tools.ort_format_model.ort_flatbuffers_py.fbs.TensorTypeAndShape import TensorTypeAndShape

ROOT = Path(__file__).resolve().parent
SOURCE_SHA256 = 'ce9623e1f58b46bc5e7485dffc6449d36255af5e9e2d877bb4db94e8c8b21ee7'


def text(value):
    return value.decode('utf-8') if value else ''


def tensor(value):
    if value.ExternalDataOffset() >= 0 or value.StringDataLength():
        raise ValueError('Unexpected external/string tensor in the pinned model')
    result = helper.make_tensor(text(value.Name()), value.DataType(),
                                [value.Dims(i) for i in range(value.DimsLength())],
                                bytes(value.RawDataAsNumpy()), raw=True)
    if result.data_type == TensorProto.FLOAT16:
        # Every stored half-precision weight has an exact float32 representation.
        result = numpy_helper.from_array(numpy_helper.to_array(result).astype(np.float32), result.name)
    return result


def value_info(arg):
    info = arg.Type()
    if info.ValueType() != 1:
        raise ValueError('Unexpected non-tensor type')
    union = info.Value()
    shape = TensorTypeAndShape()
    shape.Init(union.Bytes, union.Pos)
    dims = []
    if shape.Shape():
        for i in range(shape.Shape().DimLength()):
            dim = shape.Shape().Dim(i).Value()
            dims.append(dim.DimValue() if dim.DimType() == 1 else text(dim.DimParam()) or None)
    dtype = TensorProto.FLOAT if shape.ElemType() == TensorProto.FLOAT16 else shape.ElemType()
    return helper.make_tensor_value_info(text(arg.Name()), dtype, dims)


def attribute(attr):
    kind, name = attr.Type(), text(attr.Name())
    if kind == 1: value = attr.F()
    elif kind == 2: value = attr.I()
    elif kind == 3: value = attr.S()
    elif kind == 4: value = tensor(attr.T())
    elif kind == 6: value = [attr.Floats(i) for i in range(attr.FloatsLength())]
    elif kind == 7: value = [attr.Ints(i) for i in range(attr.IntsLength())]
    elif kind == 8: value = [attr.Strings(i) for i in range(attr.StringsLength())]
    else: raise ValueError(f'Unexpected attribute type {kind}')
    return helper.make_attribute(name, value, attr_type=kind)


def build():
    source = ROOT / 'captcha.ort'
    if sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('Upstream model hash mismatch')
    model = ort_model_processor.OrtFormatModelProcessor(str(source), {}, None)._model
    graph = model.Graph()
    args = {text(graph.NodeArgs(i).Name()): value_info(graph.NodeArgs(i))
            for i in range(graph.NodeArgsLength()) if graph.NodeArgs(i).Name()}
    inputs = [args[text(graph.Inputs(i))] for i in range(graph.InputsLength())]
    outputs = [args[text(graph.Outputs(i))] for i in range(graph.OutputsLength())]
    weights = [tensor(graph.Initializers(i)) for i in range(graph.InitializersLength())]
    nodes = []
    for i in range(graph.NodesLength()):
        node = graph.Nodes(i)
        converted = helper.make_node(text(node.OpType()),
                                    [text(node.Inputs(j)) for j in range(node.InputsLength())],
                                    [text(node.Outputs(j)) for j in range(node.OutputsLength())],
                                    name=text(node.Name()), domain=text(node.Domain()))
        for j in range(node.AttributesLength()):
            attr = attribute(node.Attributes(j))
            if converted.op_type == 'Cast' and attr.name == 'to' and attr.i == TensorProto.FLOAT16:
                attr.i = TensorProto.FLOAT
            converted.attribute.append(attr)
        nodes.append(converted)
    known = {value.name for value in inputs + weights}
    ordered = []
    while nodes:
        ready = [node for node in nodes if all(not name or name in known for name in node.input)]
        if not ready:
            raise ValueError('Cyclic or unresolved model graph')
        ordered.extend(ready)
        for node in ready:
            known.update(node.output)
            nodes.remove(node)
    boundary = {value.name for value in inputs + outputs + weights}
    converted_graph = helper.make_graph(ordered, 'ChaoxingSignFaker-captcha-fp32', inputs, outputs,
                                        initializer=weights, value_info=[v for k,v in args.items() if k not in boundary])
    result = helper.make_model(converted_graph, producer_name='auto-chaoxing-tool CPU compatibility adapter',
                               opset_imports=[helper.make_opsetid(text(model.OpsetImport(i).Domain()),
                                              model.OpsetImport(i).Version()) for i in range(model.OpsetImportLength())])
    result.ir_version = 10
    helper.set_model_props(result, {'source_sha256': SOURCE_SHA256,
                                    'source_commit': '0346adf72dde1d3fea5600232c575ad2211641c3',
                                    'conversion': 'FP16 constants/types/Cast targets widened to FP32; no retraining'})
    onnx.checker.check_model(result)
    output = ROOT / 'captcha-cpu.onnx'
    onnx.save(result, output)
    print(output.name, output.stat().st_size, sha256(output.read_bytes()).hexdigest())


if __name__ == '__main__':
    build()

// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// [SPEC §D.2.5 / §F.2.4] Giao diện Blobstream.
///
/// Blobstream KHÔNG đẩy từng data_root lên Ethereum. Nó gom một DẢI block
/// Celestia, dựng cây Merkle trên các DataRootTuple = (height, data_root), và
/// đẩy MỘT gốc — DataRootTupleRoot — đánh số bằng nonce tăng dần.
///
/// Hệ quả cho Engram: cam kết phải trỏ vào DẢI chứ không vào một block, nên
/// public values mang da_commitment + da_nonce thay vì một data_root duy nhất.
/// Và cửa sổ epoch PHẢI thẳng hàng với ranh giới dải nonce, nếu không hợp đồng
/// phải kiểm hai lần và quy tắc lát kín §F.2.1 mất tính đơn giản.
interface IBlobstream {
    struct DataRootTuple {
        uint256 height;
        bytes32 dataRoot;
    }

    struct BinaryMerkleProof {
        bytes32[] sideNodes;
        uint256 key;
        uint256 numLeaves;
    }

    function verifyAttestation(
        uint256 tupleRootNonce,
        DataRootTuple memory tuple_,
        BinaryMerkleProof memory proof
    ) external view returns (bool);
}

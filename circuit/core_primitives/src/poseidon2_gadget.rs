use nova_snark::frontend::{
    num::AllocatedNum, ConstraintSystem, LinearCombination, SynthesisError,
};
use ff::Field;

use crate::Fr;

// Nhập các hằng số liên quan đến Poseidon2 từ mô-đun native.
use crate::poseidon2::{MAT_FULL, MAT_PARTIAL, RC, R_F_HALF, R_P};

/// Gadget 1: Thực thi phép tính S-box (y = x^5) bên trong mạch R1CS.
/// Phép tính này làm tiêu tốn một số lượng constraint nhất định do yêu cầu của phép nhân phi tuyến tính.
fn pow5_gadget<CS: ConstraintSystem<Fr>>(
    mut cs: CS,
    x: &AllocatedNum<Fr>,
) -> Result<AllocatedNum<Fr>, SynthesisError> {
    // Tính bình phương: x^2 = x * x
    let x2 = x.square(cs.namespace(|| "x^2"))?;
    // Tính luỹ thừa bậc 4: x^4 = x^2 * x^2
    let x4 = x2.square(cs.namespace(|| "x^4"))?;
    // Tính luỹ thừa bậc 5: x^5 = x^4 * x
    let x5 = x4.mul(cs.namespace(|| "x^5"), x)?;
    
    Ok(x5)
}

fn apply_matrix_and_rc<CS: ConstraintSystem<Fr>>(
    mut cs: CS,
    current_state: &[AllocatedNum<Fr>; 3],
    mat: &[[Fr; 3]; 3],
    rc: Option<&[Fr; 3]>,
    round_name: &str,
) -> Result<[AllocatedNum<Fr>; 3], SynthesisError> {
    let mut next_state = vec![];

    for i in 0..3 {
        let mut lc = LinearCombination::<Fr>::zero();
        if let Some(c) = rc {
            lc = lc + (c[i], CS::one());
        }
        for j in 0..3 {
            lc = lc + (mat[i][j], current_state[j].get_variable());
        }

        let val = current_state[0].get_value().map(|_| {
            let mut sum = rc.map(|c| c[i]).unwrap_or(Fr::ZERO);
            for j in 0..3 {
                if let Some(v) = current_state[j].get_value() {
                    sum += mat[i][j] * v;
                }
            }
            sum
        });

        let new_var = AllocatedNum::alloc(
            cs.namespace(|| format!("{}_state_{}", round_name, i)),
            || val.ok_or(SynthesisError::AssignmentMissing),
        )?;

        cs.enforce(
            || format!("enforce_lc_{}_state_{}", round_name, i),
            |_| lc,
            |lc| lc + CS::one(),
            |lc| lc + new_var.get_variable(),
        );
        next_state.push(new_var);
    }

    Ok([next_state[0].clone(), next_state[1].clone(), next_state[2].clone()])
}

/// Gadget 2: Triển khai quá trình hoán vị (Permutation) của thuật toán Poseidon2 thông qua R1CS.
pub fn poseidon2_permutation_gadget<CS: ConstraintSystem<Fr>>(
    mut cs: CS,
    mut state: [AllocatedNum<Fr>; 3], // Trạng thái khởi tạo với kích thước T=3.
) -> Result<[AllocatedNum<Fr>; 3], SynthesisError> {
    let mut rc_counter = 0;

    // --- 1. Phép nhân ma trận lần thứ nhất (First Matrix Multiplication) ---
        state = apply_matrix_and_rc(
        cs.namespace(|| "first_matrix_mul"),
        &state,
        &*MAT_FULL,
        None,
        "pre",
    )?;

    // --- 2. Các vòng lặp toàn phần (Full Rounds) đầu tiên ---
    for r in 0..R_F_HALF {
        let mut pre_sbox = vec![];
        for i in 0..3 {
            let val = state[i].get_value().map(|v| v + RC[rc_counter][i]);
            let var = AllocatedNum::alloc(
                cs.namespace(|| format!("ff_round_{}_add_rc_{}", r, i)),
                || val.ok_or(SynthesisError::AssignmentMissing),
            )?;
            cs.enforce(
                || format!("ff_round_{}_enforce_rc_{}", r, i),
                |lc| lc + state[i].get_variable() + (RC[rc_counter][i], CS::one()),
                |lc| lc + CS::one(),
                |lc| lc + var.get_variable(),
            );
            pre_sbox.push(var);
        }
        rc_counter += 1;

        let mut post_sbox = vec![];
        for i in 0..3 {
            post_sbox.push(pow5_gadget(
                cs.namespace(|| format!("ff_round_{}_sbox_{}", r, i)),
                &pre_sbox[i],
            )?);
        }

        let post_sbox_arr = [post_sbox[0].clone(), post_sbox[1].clone(), post_sbox[2].clone()];
        state = apply_matrix_and_rc(
            cs.namespace(|| format!("ff_round_{}_mix", r)),
            &post_sbox_arr,
            &*MAT_FULL,
            None,
            &format!("ff_r{}", r),
        )?;
    }

    // --- 3. Các vòng lặp bán phần (Partial Rounds) ở giữa ---
    for r in 0..R_P {
        let mut pre_sbox = vec![];
        for i in 0..3 {
            let val = state[i].get_value().map(|v| v + RC[rc_counter][i]);
            let var = AllocatedNum::alloc(
                cs.namespace(|| format!("p_round_{}_add_rc_{}", r, i)),
                || val.ok_or(SynthesisError::AssignmentMissing),
            )?;
            cs.enforce(
                || format!("p_round_{}_enforce_rc_{}", r, i),
                |lc| lc + state[i].get_variable() + (RC[rc_counter][i], CS::one()),
                |lc| lc + CS::one(),
                |lc| lc + var.get_variable(),
            );
            pre_sbox.push(var);
        }
        rc_counter += 1;

        // Ở vòng lặp bán phần, phép tính S-box chỉ được áp dụng cho phần tử đầu tiên (state[0]).
        let sbox_out = pow5_gadget(
            cs.namespace(|| format!("p_round_{}_sbox_0", r)),
            &pre_sbox[0],
        )?;
        let post_sbox_arr = [sbox_out, pre_sbox[1].clone(), pre_sbox[2].clone()];

        state = apply_matrix_and_rc(
            cs.namespace(|| format!("p_round_{}_mix", r)),
            &post_sbox_arr,
            &*MAT_PARTIAL,
            None,
            &format!("p_r{}", r),
        )?;
    }

    // --- 4. Các vòng lặp toàn phần (Full Rounds) cuối cùng ---
    for r in 0..R_F_HALF {
        let mut pre_sbox = vec![];
        for i in 0..3 {
            let val = state[i].get_value().map(|v| v + RC[rc_counter][i]);
            let var = AllocatedNum::alloc(
                cs.namespace(|| format!("lf_round_{}_add_rc_{}", r, i)),
                || val.ok_or(SynthesisError::AssignmentMissing),
            )?;
            cs.enforce(
                || format!("lf_round_{}_enforce_rc_{}", r, i),
                |lc| lc + state[i].get_variable() + (RC[rc_counter][i], CS::one()),
                |lc| lc + CS::one(),
                |lc| lc + var.get_variable(),
            );
            pre_sbox.push(var);
        }
        rc_counter += 1;

        let mut post_sbox = vec![];
        for i in 0..3 {
            post_sbox.push(pow5_gadget(
                cs.namespace(|| format!("lf_round_{}_sbox_{}", r, i)),
                &pre_sbox[i],
            )?);
        }

        let post_sbox_arr = [post_sbox[0].clone(), post_sbox[1].clone(), post_sbox[2].clone()];
        state = apply_matrix_and_rc(
            cs.namespace(|| format!("lf_round_{}_mix", r)),
            &post_sbox_arr,
            &*MAT_FULL,
            None,
            &format!("lf_r{}", r),
        )?;
    }

    Ok(state)
}

/// Gadget 3: API tiện ích phục vụ cho quá trình băm (hash) 2 phần tử, chủ yếu được sử dụng trong Challenge Binding và Merkle Path.
pub fn hash_2_gadget<CS: ConstraintSystem<Fr>>(
    mut cs: CS,
    left: &AllocatedNum<Fr>,
    right: &AllocatedNum<Fr>,
) -> Result<AllocatedNum<Fr>, SynthesisError> {
    // Khởi tạo phần tử thứ 3 làm miền phân cách (Domain Separator) bằng 0 và thêm ràng buộc (enforce) trong mạch.
    let zero = AllocatedNum::alloc(cs.namespace(|| "zero_domain_sep"), || Ok(Fr::ZERO))?;
    // Ràng buộc giá trị zero = 0: zero * 1 = 0 (dưới dạng A*B=C với A=zero, B=1, C=0).
    cs.enforce(
        || "enforce_zero",
        |lc| lc + zero.get_variable(),
        |lc| lc + CS::one(),
        |lc| lc,
    );

    let state = [left.clone(), right.clone(), zero];
    let out_state = poseidon2_permutation_gadget(cs.namespace(|| "poseidon2_perm"), state)?;
    
    // Trả về phần tử đầu tiên từ trạng thái đầu ra của hàm băm.
    Ok(out_state[0].clone())
}
/// Gadget 4: Hàm băm (hash) 4 phần tử, được sử dụng cho các quá trình Replica Reconstruction và Challenge Binding.
pub fn hash_4_gadget<CS: ConstraintSystem<Fr>>(
    mut cs: CS,
    a: &AllocatedNum<Fr>,
    b: &AllocatedNum<Fr>,
    c: &AllocatedNum<Fr>,
    d: &AllocatedNum<Fr>,
) -> Result<AllocatedNum<Fr>, SynthesisError> {
    let left = hash_2_gadget(cs.namespace(|| "hash_4_left"), a, b)?;
    let right = hash_2_gadget(cs.namespace(|| "hash_4_right"), c, d)?;
    hash_2_gadget(cs.namespace(|| "hash_4_final"), &left, &right)
}

/// Gadget 5: Thực hiện hoán đổi 2 phần tử dựa trên điều kiện boolean, thường dùng trong quá trình xác thực Merkle Path.
/// - Nếu điều kiện (condition) là 1 (true), hàm sẽ trả về (b, a).
/// - Nếu điều kiện (condition) là 0 (false), hàm sẽ trả về (a, b).
pub fn conditional_swap_gadget<CS: ConstraintSystem<Fr>>(
    mut cs: CS,
    a: &AllocatedNum<Fr>,
    b: &AllocatedNum<Fr>,
    condition: &AllocatedNum<Fr>, // Biến điều kiện boolean, chỉ nhận giá trị 0 hoặc 1.
) -> Result<(AllocatedNum<Fr>, AllocatedNum<Fr>), SynthesisError> {
    // Tính toán giá trị bên trái: left = a + condition * (b - a).
    let left_val = condition.get_value().and_then(|c_val| {
        a.get_value().and_then(|a_val| {
            b.get_value().map(|b_val| a_val + c_val * (b_val - a_val))
        })
    });
    let left = AllocatedNum::alloc(cs.namespace(|| "left"), || left_val.ok_or(SynthesisError::AssignmentMissing))?;
    cs.enforce(
        || "calc_left",
        |lc| lc + condition.get_variable(),
        |lc| lc + b.get_variable() - a.get_variable(),
        |lc| lc + left.get_variable() - a.get_variable(),
    );

    // Tính toán giá trị bên phải: right = b - condition * (b - a).
    let right_val = condition.get_value().and_then(|c_val| {
        a.get_value().and_then(|a_val| {
            b.get_value().map(|b_val| b_val - c_val * (b_val - a_val))
        })
    });
    let right = AllocatedNum::alloc(cs.namespace(|| "right"), || right_val.ok_or(SynthesisError::AssignmentMissing))?;
    cs.enforce(
        || "calc_right",
        |lc| lc + condition.get_variable(),
        |lc| lc + b.get_variable() - a.get_variable(),
        |lc| lc + b.get_variable() - right.get_variable(),
    );

    Ok((left, right))
}
/// Gadget 6: hash_chain — Hàm băm dạng chuỗi, đóng vai trò tương đương với hàm poseidon2_chain() trong simulator_runner.
///
/// Mô phỏng quá trình poseidon2_chain([v0, v1, v2, v3]):
///   acc = 0
///   acc = hash_2(acc, v0)
///   acc = hash_2(acc, v1)
///   acc = hash_2(acc, v2)
///   acc = hash_2(acc, v3)
///   return acc
///
/// Chú ý: Hàm này thực thi việc băm tuần tự thành một chuỗi, hoàn toàn KHÁC BIỆT so với phương pháp băm cây nhị phân trong hash_4.
/// Hàm này được thiết kế riêng cho tiến trình Challenge Binding nhằm đảm bảo tính đồng bộ với hàm derive_challenge_index() tại máy chủ (host).
pub fn hash_chain_gadget<CS: ConstraintSystem<Fr>>(
    mut cs: CS,
    values: &[&AllocatedNum<Fr>],
) -> Result<AllocatedNum<Fr>, SynthesisError> {
    // Khởi tạo giá trị tích lũy ban đầu: acc_0 = 0.
    let mut acc = AllocatedNum::alloc(cs.namespace(|| "chain_acc_init"), || Ok(Fr::ZERO))?;
    cs.enforce(
        || "chain_acc_init_zero",
        |lc| lc + acc.get_variable(),
        |lc| lc + CS::one(),
        |lc| lc,
    );

    for (i, &val) in values.iter().enumerate() {
        acc = hash_2_gadget(
            cs.namespace(|| format!("chain_step_{}", i)),
            &acc,
            val,
        )?;
    }

    Ok(acc)
}

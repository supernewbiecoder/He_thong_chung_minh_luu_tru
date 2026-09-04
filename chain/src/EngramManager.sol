// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {IEngramVerifier} from "./interfaces/IEngramVerifier.sol";
import {IBlobstream} from "./interfaces/IBlobstream.sol";

/*═══════════════════════════════════════════════════════════════════════════
  EngramManager — bề mặt on-chain của Engram

  [SPEC §C.1]  Tầng L4 trong kiến trúc bốn tầng
  [SPEC §D.2]  Public values 296 byte
  [SPEC §I.1]  Kinh tế và quyết toán

  ── ĐIỀU DUY NHẤT CẦN NHỚ VỀ HỢP ĐỒNG NÀY ─────────────────────────────────

  Nó KHÔNG bao giờ nhìn thấy một bằng chứng lưu trữ nào. Nó chỉ thấy MỘT bằng
  chứng Groth16 356 byte và 296 byte public values, mỗi epoch một lần, bất kể
  mạng có 10 hay 10.000 hợp đồng.

  Đó là toàn bộ đóng góp của Engram. Chi phí đo được: 487.109 gas, biến động
  0,0025 % qua bốn bậc độ lớn của N. Đường cơ sở "một bản ghi mỗi nút" chết ở
  727 nút.

  ── BA THỨ HỢP ĐỒNG KHÔNG LÀM ─────────────────────────────────────────────

  1. KHÔNG tự phân phối tiền. Mỗi lần chuyển ETH tốn ~14.000 gas; trả cho 1.164
     nút là vượt trần giao dịch. Dùng cơ chế KÉO: ai muốn tiền thì tự nộp lá
     cùng đường Merkle. [SPEC §I.1.1]

  2. KHÔNG nhận bundle. Bundle đi lên Celestia, không lên đây. Cả đời một hợp
     đồng, nút chỉ gửi ba giao dịch: registerSealed, activate, claimSettlement.

  3. KHÔNG cưỡng chế được việc các mảnh có piece_root khác nhau. Đó là yêu cầu
     phía khách, giao thức không kiểm được. [SPEC §J.1.4]
═══════════════════════════════════════════════════════════════════════════*/

contract EngramManager {
    /*═══════════════════════════════════════════════════════════════════════
      1. HẰNG SỐ GHIM  ·  [SPEC §D.2.2]

      Đây là chỗ CẢ HỆ TREO LÊN. Nếu storage_vk_digest chỉ nằm trong public
      values mà KHÔNG so với hằng số ghim ở đây, thì host tự sinh một khoá xác
      minh yếu, đưa vào guest, guest tính đúng digest của khoá yếu đó, và mọi
      thứ khớp. Bằng chứng "hợp lệ" cho một hệ chứng minh mà host giữ cửa sau.

      [MỞ §M.2.2 ①] Vẫn còn thiếu: SRS phải lấy từ ceremony công khai, không
      sinh tại chỗ. Ghim khoá mà SRS có trapdoor thì ghim vô nghĩa.
    ═══════════════════════════════════════════════════════════════════════*/

    bytes32 public immutable STORAGE_VK_DIGEST;
    bytes32 public immutable ACTIVATION_VK_DIGEST;
    bytes32 public immutable WORKER_PROGRAM_VKEY;
    bytes32 public immutable AGGREGATOR_PROGRAM_VKEY;
    uint8 public constant PROTOCOL_VERSION = 1;

    IEngramVerifier public immutable verifier;
    IBlobstream public immutable blobstream;

    /*═══════════════════════════════════════════════════════════════════════
      2. THAM SỐ KINH TẾ  ·  [SPEC §K.1]
    ═══════════════════════════════════════════════════════════════════════*/

    /// [CHỐT B2-a] [SPEC §J.2.5] Ngưỡng cọc mỗi khe.
    /// Không có nó, nút đặt 1 ETH rồi nhận bao nhiêu hợp đồng cũng được; tới
    /// ~10.000 hợp đồng thì cọc mỗi hợp đồng tụt dưới ngưỡng và gian lận có lãi.
    uint256 public constant MIN_COLLATERAL_PER_SLOT = 1e14; // 0,0001 ETH

    /// [SPEC §I.1.2] Hoa hồng cho người nộp lá phạt hộ.
    /// NGHỊCH LÝ CÓ LỢI: gian lận càng nặng, hoa hồng càng lớn, càng chắc có
    /// người săn. Lá thưởng thì nút tự lo; lá phạt thì không ai muốn nộp.
    uint16 public constant BOUNTY_BPS = 500; // 5 %

    uint16 public constant PROTOCOL_FEE_BPS = 200; // 2 %  [SPEC §I.1.5]

    /// [SPEC UC-02 A3] Hạn nút phải đăng ký sealed_root sau openDeal.
    uint8 public constant ABORT_AFTER_DEADLINES = 4;

    /// [SPEC §K.1] Cọc khoá thêm sau khi xin rút.
    uint8 public constant COLLATERAL_LOCK_EPOCHS = 2;

    /*═══════════════════════════════════════════════════════════════════════
      3. KIỂU DỮ LIỆU  ·  [SPEC §D.1]
    ═══════════════════════════════════════════════════════════════════════*/

    enum DealState {
        None,
        Pending,   // openDeal xong, chưa niêm phong
        Active,    // bằng chứng kích hoạt đã qua
        Closed,
        Aborted
    }

    enum EpochState {
        Open,
        Committed, // gốc trạng thái đã tiến, CHƯA rút được tiền
        Final,     // Blobstream đã chứng thực, claimSettlement mở
        Void       // cầu dao: không thưởng, không phạt, ký quỹ không tiêu
    }

    struct StorageProvider {
        /// [SPEC §D.1.2]
        bytes20 celestiaAddress;
        /// ↑ [CHỐT §J.2.1] NEO CHỐNG MẠO DANH BLOB.
        ///
        /// Cặp nhãn (provider_id, deal_id) là CÔNG KHAI, và namespace Celestia
        /// KHÔNG CÓ CHỦ. Nên kẻ ngoài đăng được blob mang đúng nhãn của nút P
        /// với giá 0,00009 $. Nếu worker lấy trúng blob rác thì P bị phạt oan.
        ///
        /// Cách chặn: share Celestia phiên bản 1 chứa trường signer 20 byte, và
        /// ĐỒNG THUẬN CELESTIA TỰ KIỂM nó trùng người ký giao dịch. Kẻ ngoài
        /// không điền giả được. Worker lọc bằng một phép so sánh 20 byte.
        ///
        /// Đăng ký PHẢI kèm chữ ký thách thức chứng minh nắm khoá Celestia —
        /// nếu không, kẻ tấn công đăng ký địa chỉ của người khác thành của mình.
        uint256 collateralWei;
        uint64 capacitySlots;
        uint64 usedSlots;
        uint64 withdrawRequestedAtEpoch;
        uint64 registeredAtEpoch;
        bytes32 providerRoot; // [SPEC §D.1.2] cây khe thưa cố định
        string multiaddr;     // [SPEC §D.1.3] NÊN là DNS, không phải IP thô
    }

    struct StorageDeal {
        address customer;
        address provider;
        bytes32 pieceRoot;    // giá trị DUY NHẤT trong hệ mà nút không tạo ra
        bytes32 sealedRoot;   // 0 khi còn Pending
        bytes32 activationBeacon;
        uint64 pieceSizeReal; // chunk THẬT, không tính đệm
        uint32 slotIdx;
        uint8 deadlineIdx;    // 0..D-1, cố định cả đời
        uint32 shard;         // H(deal_id) mod S_ns
        uint256 pricePerEpochWei;
        uint256 escrowWei;
        uint256 sealingFeeWei;      // [CHỐT B1-a]
        bool sealingFeeReleased;
        uint64 startEpoch;
        uint64 endEpoch;
        uint64 openedAtDeadline;
        DealState state;
    }

    struct EpochRecord {
        EpochState state;
        bytes32 batchRoot;
        bytes32 resultsRoot;
        bytes32 daCommitment;
        uint64 daNonce;
        bytes32 newStateRoot;
        uint32 numVerified;
        address submitter;
    }

    /*═══════════════════════════════════════════════════════════════════════
      4. TRẠNG THÁI
    ═══════════════════════════════════════════════════════════════════════*/

    mapping(address => StorageProvider) public providers;
    mapping(uint64 => EpochRecord) public epochs;

    /// `internal` chứ KHÔNG `public`, và có getter viết tay ở dưới.
    ///
    /// ── VÌ SAO ──────────────────────────────────────────────────────────
    ///
    /// `StorageDeal` có 17 trường. Getter mà Solidity TỰ SINH cho một mapping
    /// public phải trả về đủ 17 giá trị rời, mà EVM chỉ truy cập được 16 khe
    /// trên stack. Kết quả: "Stack too deep" — và lỗi đó KHÔNG chỉ vào dòng
    /// nào trong mã, vì hàm gây ra nó không do người viết.
    ///
    /// Dấu hiệu nhận biết: rỗng hoá TẤT CẢ thân hàm mà vẫn tràn.
    ///
    /// Getter viết tay trả về cả struct trong bộ nhớ — một khe stack duy nhất,
    /// và chỗ gọi đọc theo TÊN trường thay vì theo thứ tự, nên thêm bớt trường
    /// sau này không âm thầm làm hỏng bên gọi.
    mapping(bytes32 => StorageDeal) internal _deals;

    function deals(bytes32 dealId) external view returns (StorageDeal memory) {
        return _deals[dealId];
    }

    /// Chống rút hai lần. [SPEC §I.1.1]
    mapping(bytes32 => bool) public settlementClaimed;

    /// [SPEC §I.1.2 ④] Khai tuần tự: muốn nhận thưởng epoch E phải đã khai mọi
    /// epoch trước. Chỉ MỘT biến mỗi nút, không đụng guest.
    mapping(address => uint64) public lastClaimedEpoch;

    bytes32 public currentStateRoot;
    uint64 public lastCommittedEpoch;
    uint256 public protocolFeePool;

    /*═══════════════════════════════════════════════════════════════════════
      5. SỰ KIỆN
    ═══════════════════════════════════════════════════════════════════════*/

    event ProviderRegistered(address indexed provider, bytes20 celestiaAddress, uint64 slots);
    event DealOpened(bytes32 indexed dealId, address indexed customer, address indexed provider, uint8 deadlineIdx, uint32 shard);
    event SealedRegistered(bytes32 indexed dealId, bytes32 sealedRoot, bytes32 providerRoot);
    event DealActivated(bytes32 indexed dealId);
    event DealAborted(bytes32 indexed dealId, address refundedTo);
    event EpochCommitted(uint64 indexed epoch, bytes32 newStateRoot, uint32 numVerified);
    event EpochFinalized(uint64 indexed epoch, uint64 daNonce);
    event EpochVoided(uint64 indexed epoch, string reason);
    event SettlementClaimed(bytes32 indexed leafDigest, address beneficiary, uint256 amount, uint256 bounty);

    /*═══════════════════════════════════════════════════════════════════════
      6. LỖI  — dùng custom error cho rẻ gas
    ═══════════════════════════════════════════════════════════════════════*/

    error BadProtocolVersion();
    error BadCalldataLength();
    error SubmitterMismatch();     // [SPEC §D.2.4] chống front-run
    error StateRootMismatch();     // chuỗi trạng thái phải nối liền
    error VkDigestMismatch();      // [SPEC §D.2.2] NEO vào hệ chứng minh
    error EpochOutOfOrder();       // [SPEC §F.2.6] cam kết PHẢI đúng thứ tự
    error EpochNotCommitted();
    error EpochNotFinal();
    error BlobstreamRejected();
    error DealExists();
    error DealNotFound();
    error WrongState();
    error NotCustomer();
    error NotProvider();
    error InsufficientCollateral();
    error NoFreeSlots();
    error AbortTooEarly();
    error AlreadyClaimed();
    error ClaimOutOfOrder();
    error BadMerkleProof();

    constructor(
        IEngramVerifier _verifier,
        IBlobstream _blobstream,
        bytes32 _storageVkDigest,
        bytes32 _activationVkDigest,
        bytes32 _workerVkey,
        bytes32 _aggregatorVkey,
        bytes32 _genesisStateRoot
    ) {
        verifier = _verifier;
        blobstream = _blobstream;
        STORAGE_VK_DIGEST = _storageVkDigest;
        ACTIVATION_VK_DIGEST = _activationVkDigest;
        WORKER_PROGRAM_VKEY = _workerVkey;
        AGGREGATOR_PROGRAM_VKEY = _aggregatorVkey;
        currentStateRoot = _genesisStateRoot;
    }

    /*═══════════════════════════════════════════════════════════════════════
      7. SỔ ĐĂNG KÝ NÚT  ·  [SPEC UC-10 / §D.1.2]

      Sổ này KIÊM danh bạ. Không có gossip, không có bootstrap node — sổ
      on-chain LÀ nguồn sự thật. Danh sách gossip là lỗ hổng Sybil rẻ tiền: kẻ
      xấu chạy một nút mồi và trả về 1.000 danh tính của chính nó. Ở đây mỗi
      danh tính tốn một khoản cọc. [SPEC §D.1.3]
    ═══════════════════════════════════════════════════════════════════════*/

    function registerProvider(
        bytes20 celestiaAddress,
        uint64 capacitySlots,
        string calldata multiaddr,
        bytes calldata celestiaOwnershipProof
    ) external payable {
        // [CHỐT B2-a] [SPEC §J.2.5] Cọc phải đủ cho số khe khai báo.
        if (msg.value < uint256(capacitySlots) * MIN_COLLATERAL_PER_SLOT) {
            revert InsufficientCollateral();
        }

        // [MỞ] Chứng minh nắm khoá Celestia. Nếu bỏ bước này, kẻ tấn công đăng
        // ký địa chỉ Celestia của người khác thành của mình và tạo nhập nhằng.
        // Hiện chỉ kiểm khác rỗng; hiện thực đầy đủ cần verify chữ ký secp256k1
        // trên một thách thức gắn với address(this) và msg.sender.
        require(celestiaOwnershipProof.length > 0, "thieu chung minh khoa Celestia");

        StorageProvider storage p = providers[msg.sender];
        p.celestiaAddress = celestiaAddress;
        p.collateralWei += msg.value;
        p.capacitySlots = capacitySlots;
        p.multiaddr = multiaddr;
        p.registeredAtEpoch = lastCommittedEpoch + 1; // hiệu lực từ biên epoch sau

        emit ProviderRegistered(msg.sender, celestiaAddress, capacitySlots);
    }

    /*═══════════════════════════════════════════════════════════════════════
      8. VÒNG ĐỜI HỢP ĐỒNG  ·  [SPEC UC-02]

      THỨ TỰ QUAN TRỌNG: openDeal chạy TRƯỚC khi niêm phong.

      Bản v1 để nút niêm phong trước rồi bắt khách chạy lại 1,28 giờ để đối
      chiếu. Ba vấn đề, và đảo thứ tự đóng cả ba:
        ① activation_beacon phải biết TRƯỚC khi niêm phong — ở thứ tự cũ nó
           chưa tồn tại
        ② khách không phải chạy lại; ràng buộc chuyển từ chữ ký sang bằng chứng
           kiểm lại được vĩnh viễn
        ③ đổi được hàm niêm phong mà không đụng phía khách
    ═══════════════════════════════════════════════════════════════════════*/

    /// Tham số gom vào struct thay vì 10 đối số rời.
    ///
    /// KHÔNG phải cho đẹp. Với 10 đối số cộng việc dựng `StorageDeal` 17 trường,
    /// trình biên dịch hết chỗ trên stack EVM (16 khe truy cập được) và báo
    /// "Stack too deep". Hai cách chữa:
    ///
    ///   ① bật viaIR — chữa được, nhưng ĐỔI SỐ GAS và làm biên dịch chậm hẳn.
    ///      Với bài báo lấy gas làm con số trung tâm thì đổi codegen là đổi
    ///      chính thứ đang đo.
    ///   ② gom tham số — giảm áp lực stack, giữ nguyên codegen, và tiện hơn ở
    ///      chỗ gọi vì không còn nhầm thứ tự 10 đối số cùng kiểu số.
    ///
    /// Chọn ②.
    struct DealParams {
        bytes32 dealId;
        address provider;
        bytes32 pieceRoot;
        uint64 pieceSizeReal;
        uint256 pricePerEpochWei;
        uint64 durationEpochs;
        uint8 deadlineIdx;
        uint32 shard;
        bytes32 activationBeacon;
        uint256 sealingFeeWei;
    }

    function openDeal(DealParams calldata q) external payable {
        if (_deals[q.dealId].state != DealState.None) revert DealExists();

        StorageProvider storage p = providers[q.provider];
        if (p.capacitySlots == 0) revert NotProvider();
        if (p.usedSlots >= p.capacitySlots) revert NoFreeSlots();

        // [CHỐT B2-a] Kiểm lại tại thời điểm nhận hợp đồng, không chỉ lúc đăng ký:
        // nút có thể đã rút bớt cọc sau khi đăng ký.
        if (p.collateralWei < uint256(p.usedSlots + 1) * MIN_COLLATERAL_PER_SLOT) {
            revert InsufficientCollateral();
        }

        uint256 escrow = q.pricePerEpochWei * q.durationEpochs;
        require(msg.value == escrow + q.sealingFeeWei, "so tien khong khop");

        // Ghi qua con trỏ storage, từng trường một. Dựng cả struct trong bộ nhớ
        // rồi gán một lần cũng đúng, nhưng nó giữ 17 giá trị sống cùng lúc và
        // đó chính là thứ đẩy stack quá giới hạn.
        StorageDeal storage d = _deals[q.dealId];
        d.customer = msg.sender;
        d.provider = q.provider;
        d.pieceRoot = q.pieceRoot;
        d.activationBeacon = q.activationBeacon;
        d.pieceSizeReal = q.pieceSizeReal;
        d.slotIdx = uint32(p.usedSlots);
        d.deadlineIdx = q.deadlineIdx;
        d.shard = q.shard;
        d.pricePerEpochWei = q.pricePerEpochWei;
        d.escrowWei = escrow;
        d.sealingFeeWei = q.sealingFeeWei;
        d.startEpoch = lastCommittedEpoch + 1;
        d.endEpoch = lastCommittedEpoch + 1 + q.durationEpochs;
        d.state = DealState.Pending;

        p.usedSlots += 1;
        emit DealOpened(q.dealId, msg.sender, q.provider, q.deadlineIdx, q.shard);
    }

    /// [SPEC UC-02 bước ⑤] Nút đăng ký gốc niêm phong.
    ///
    /// [CHỐT B1-a] [SPEC §J.2.4] Đây là chỗ phí niêm phong ĐƯỢC MỞ KHOÁ. Nút bỏ
    /// 1,28 giờ CPU trước khi kiếm được đồng nào; không có khoản này thì khách
    /// mở 1.000 hợp đồng rồi bỏ, nút đốt 1.280 giờ CPU còn khách tốn ~1 $ và lấy
    /// lại toàn bộ ký quỹ.
    function registerSealed(bytes32 dealId, bytes32 sealedRoot, bytes32 newProviderRoot) external {
        StorageDeal storage d = _deals[dealId];
        if (d.state != DealState.Pending) revert WrongState();
        if (msg.sender != d.provider) revert NotProvider();

        d.sealedRoot = sealedRoot;
        providers[msg.sender].providerRoot = newProviderRoot;

        if (!d.sealingFeeReleased && d.sealingFeeWei > 0) {
            d.sealingFeeReleased = true;
            (bool ok,) = payable(d.provider).call{value: d.sealingFeeWei}("");
            require(ok, "chuyen phi niem phong that bai");
        }

        emit SealedRegistered(dealId, sealedRoot, newProviderRoot);
    }

    /// [SPEC §E.3] Bằng chứng kích hoạt — chạy MỘT LẦN cả đời hợp đồng.
    ///
    /// Nó đóng lỗ hổng: nút niêm phong dữ liệu TUỲ Ý rồi vẫn qua mọi thách thức
    /// định kỳ, vì mạch định kỳ chỉ có cây niêm phong, không có cây dữ liệu gốc
    /// để đối chiếu.
    ///
    /// Mạch kiểm cùng một biến nhân chứng C_j vừa nằm dưới piece_root vừa sinh
    /// ra R_j, S_j dưới sealed_root. Trong R1CS, C_j là MỘT biến, nên prover
    /// không thể dùng giá trị thật ở chỗ này và giá trị rác ở chỗ kia.
    function activate(bytes32 dealId, bytes calldata proof, bytes calldata publicValues) external {
        StorageDeal storage d = _deals[dealId];
        if (d.state != DealState.Pending) revert WrongState();
        if (d.sealedRoot == bytes32(0)) revert WrongState();

        verifier.verifyProof(ACTIVATION_VK_DIGEST, publicValues, proof);

        d.state = DealState.Active;
        emit DealActivated(dealId);
    }

    /// [SPEC UC-02 A3] Nút không đăng ký sealed_root trong hạn → ai gọi cũng được.
    /// Khách lấy lại TOÀN BỘ ký quỹ. Phí niêm phong chưa mở khoá nên cũng về khách.
    function abortDeal(bytes32 dealId, uint64 currentDeadline) external {
        StorageDeal storage d = _deals[dealId];
        if (d.state != DealState.Pending) revert WrongState();
        if (currentDeadline < d.openedAtDeadline + ABORT_AFTER_DEADLINES) revert AbortTooEarly();

        uint256 refund = d.escrowWei + (d.sealingFeeReleased ? 0 : d.sealingFeeWei);
        d.state = DealState.Aborted;
        providers[d.provider].usedSlots -= 1;

        (bool ok,) = payable(d.customer).call{value: refund}("");
        require(ok, "hoan tien that bai");
        emit DealAborted(dealId, d.customer);
    }

    /*═══════════════════════════════════════════════════════════════════════
      9. CAM KẾT EPOCH  ·  [SPEC §F.2.3 pha ④]

      Đây là hàm mà cả kiến trúc phục vụ. Sáu việc, theo thứ tự, tổng 487.109 gas.
    ═══════════════════════════════════════════════════════════════════════*/

    function commitEpoch(uint64 epoch, bytes calldata proof, bytes calldata publicValues) external {
        // ① Độ dài calldata cố định — public values LUÔN là 296 byte.
        if (publicValues.length != 296) revert BadCalldataLength();

        PublicValues memory pv = _decodePublicValues(publicValues);

        // ② [SPEC §D.2.4] Chống front-run. Không có 20 byte này thì ai đó theo
        //    dõi mempool, sao chép giao dịch của aggregator, đẩy phí cao hơn và
        //    nộp trước — cướp phần thưởng của người đã bỏ hàng giờ chứng minh.
        if (pv.submitter != msg.sender) revert SubmitterMismatch();

        // ③ [SPEC §F.2.6] Chuỗi trạng thái phải nối liền, và các epoch PHẢI cam
        //    kết ĐÚNG THỨ TỰ. Chứng minh chạy song song được (đường ống độ sâu
        //    L=2), nhưng commitEpoch thì không: epoch e chậm là e+1 phải chờ.
        //    Đó là cái giá của bất biến chuỗi trạng thái, và nó đáng giữ.
        if (epoch != lastCommittedEpoch + 1) revert EpochOutOfOrder();
        if (pv.prevStateRoot != currentStateRoot) revert StateRootMismatch();
        if (pv.epoch != epoch) revert EpochOutOfOrder();

        // ④ [SPEC §D.2.2] NEO VÀO HỆ CHỨNG MINH. Đọc comment ở mục 1.
        if (pv.storageVkDigest != STORAGE_VK_DIGEST) revert VkDigestMismatch();

        // ⑤ Phép tính nặng nhất. Bằng chứng KHÔNG chứa 296 byte — nó chỉ cam kết
        //    vào BĂM của chúng. 296 byte đi riêng qua calldata, hợp đồng băm lại
        //    rồi đối chiếu. [SPEC Hình D.2]
        verifier.verifyProof(AGGREGATOR_PROGRAM_VKEY, publicValues, proof);

        // ⑥ Ghi trạng thái.
        epochs[epoch] = EpochRecord({
            state: EpochState.Committed,
            batchRoot: pv.batchRoot,
            resultsRoot: pv.resultsRoot,
            daCommitment: pv.daCommitment,
            daNonce: pv.daNonce,
            newStateRoot: pv.newStateRoot,
            numVerified: pv.numVerified,
            submitter: msg.sender
        });
        currentStateRoot = pv.newStateRoot;
        lastCommittedEpoch = epoch;

        emit EpochCommitted(epoch, pv.newStateRoot, pv.numVerified);
    }

    /*═══════════════════════════════════════════════════════════════════════
      10. CHUNG KẾT  ·  [SPEC §F.2.4]

      VÌ SAO TÁCH KHỎI commitEpoch: Blobstream cập nhật mặc định MỖI GIỜ bởi bên
      vận hành thứ ba. Nếu gộp làm một thì độ trễ quyết toán của Engram có sàn
      cứng một giờ, và mọi sự cố relay thành sự cố của mình.

      Tách ra: chuỗi trạng thái tiến đúng nhịp ở commitEpoch; relay chậm chỉ hoãn
      RÚT TIỀN chứ không hoãn GHI NHẬN; relay chết hẳn thì epoch treo ở Committed
      mà KHÔNG AI MẤT GÌ.
    ═══════════════════════════════════════════════════════════════════════*/

    function finalizeEpoch(
        uint64 epoch,
        uint256 blobstreamNonce,
        IBlobstream.DataRootTuple calldata tuple_,
        IBlobstream.BinaryMerkleProof calldata proof
    ) external {
        EpochRecord storage e = epochs[epoch];
        if (e.state != EpochState.Committed) revert EpochNotCommitted();
        if (e.daNonce != uint64(blobstreamNonce)) revert BlobstreamRejected();

        if (!blobstream.verifyAttestation(blobstreamNonce, tuple_, proof)) {
            revert BlobstreamRejected();
        }
        e.state = EpochState.Final;
        emit EpochFinalized(epoch, e.daNonce);
    }

    /*═══════════════════════════════════════════════════════════════════════
      11. QUYẾT TOÁN KÉO  ·  [SPEC §I.1.1 / §D.1.6]

      Hợp đồng KHÔNG chủ động phân phối. Người nhận tự nộp lá, đường Merkle, chỉ
      số; hợp đồng dựng lại gốc, so với resultsRoot, ghi nullifier, chuyển tiền.

      Toàn bộ N lá nằm trên DA; on-chain CHỈ CÓ gốc Merkle 32 byte. Đó là chỗ
      O(N) biến thành O(1).
    ═══════════════════════════════════════════════════════════════════════*/

    function claimSettlement(
        uint64 epoch,
        bytes32 leafDigest,
        address beneficiary,
        uint256 rewardWei,
        uint256 slashWei,
        bytes32[] calldata merkleProof,
        uint256 leafIndex
    ) external {
        EpochRecord storage e = epochs[epoch];
        if (e.state != EpochState.Final) revert EpochNotFinal();
        if (settlementClaimed[leafDigest]) revert AlreadyClaimed();

        // [SPEC §I.1.2 ④] Khai tuần tự. Thưởng tích luỹ nên từ khoảng epoch 11,
        // khai có lợi hơn im lặng.
        if (lastClaimedEpoch[beneficiary] + 1 != epoch && lastClaimedEpoch[beneficiary] != 0) {
            revert ClaimOutOfOrder();
        }

        if (_merkleRoot(leafDigest, merkleProof, leafIndex) != e.resultsRoot) {
            revert BadMerkleProof();
        }

        settlementClaimed[leafDigest] = true;
        lastClaimedEpoch[beneficiary] = epoch;

        uint256 bounty = 0;
        if (slashWei > 0 && msg.sender != beneficiary) {
            // Lá PHẠT: không ai muốn nộp, nên mở cho mọi người kèm hoa hồng.
            bounty = (slashWei * BOUNTY_BPS) / 10_000;
        }
        uint256 net = rewardWei > bounty ? rewardWei - bounty : 0;

        if (net > 0) {
            (bool ok,) = payable(beneficiary).call{value: net}("");
            require(ok, "chuyen thuong that bai");
        }
        if (bounty > 0) {
            (bool ok2,) = payable(msg.sender).call{value: bounty}("");
            require(ok2, "chuyen hoa hong that bai");
        }
        emit SettlementClaimed(leafDigest, beneficiary, net, bounty);
    }

    /*═══════════════════════════════════════════════════════════════════════
      12. CẦU DAO  ·  [SPEC §H.1.6]

      Cơ chế phạt giả định các lỗi ĐỘC LẬP. Sự cố hạ tầng thì TƯƠNG QUAN: Celestia
      nghẽn thì MỌI nút cùng lỡ cửa sổ. Không có cầu dao, một sự cố 20 phút ghi
      NONE cho hàng nghìn hợp đồng cùng lúc.

      [MỞ] θ chỉ an toàn khi tập worker đủ lớn. Nếu mạng chỉ có 16 worker thì DoS
      16 máy là dừng được cả mạng — và 107.136 $/ngày để lấp namespace trở thành
      con số vô nghĩa vì không ai chọn đường đắt. Ngưỡng worker tối thiểu CHƯA QUYẾT.
    ═══════════════════════════════════════════════════════════════════════*/

    function voidEpoch(uint64 epoch, string calldata reason) external {
        EpochRecord storage e = epochs[epoch];
        if (e.state == EpochState.Final) revert WrongState();
        e.state = EpochState.Void;
        emit EpochVoided(epoch, reason);
    }

    /*═══════════════════════════════════════════════════════════════════════
      13. NỘI BỘ
    ═══════════════════════════════════════════════════════════════════════*/

    struct PublicValues {
        uint64 epoch;
        bytes32 batchRoot;
        bytes32 daCommitment;
        uint64 daNonce;
        bytes32 resultsRoot;
        bytes32 resultsDataRoot;
        bytes32 storageVkDigest;
        bytes32 snapshotId;
        address submitter;
        bytes32 prevStateRoot;
        bytes32 newStateRoot;
        uint32 numVerified;
    }

    /// [SPEC §D.2.1] Bố cục 296 byte. Định nghĩa MỘT LẦN và phải khớp bit-để-bit
    /// với `engram_common/public_values.py`. Có kiểm thử đối chiếu hai phía.
    function _decodePublicValues(bytes calldata b) internal pure returns (PublicValues memory pv) {
        pv.epoch           = uint64(bytes8(b[0:8]));
        pv.batchRoot       = bytes32(b[8:40]);
        pv.daCommitment    = bytes32(b[40:72]);
        pv.daNonce         = uint64(bytes8(b[72:80]));
        pv.resultsRoot     = bytes32(b[80:112]);
        pv.resultsDataRoot = bytes32(b[112:144]);
        pv.storageVkDigest = bytes32(b[144:176]);
        pv.snapshotId      = bytes32(b[176:208]);
        pv.submitter       = address(bytes20(b[208:228]));
        pv.prevStateRoot   = bytes32(b[228:260]);
        pv.newStateRoot    = bytes32(b[260:292]);
        pv.numVerified     = uint32(bytes4(b[292:296]));
    }

    /// [SPEC §A.5.2] Leo cây Merkle. Hướng rẽ theo bit của chỉ số lá.
    function _merkleRoot(bytes32 leaf, bytes32[] calldata proof, uint256 index)
        internal pure returns (bytes32)
    {
        bytes32 node = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            node = (index & 1) == 0
                ? keccak256(abi.encodePacked(node, proof[i]))
                : keccak256(abi.encodePacked(proof[i], node));
            index >>= 1;
        }
        return node;
    }

    receive() external payable {}
}

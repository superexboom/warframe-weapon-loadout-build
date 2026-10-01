
/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void FUN_140a3e6c0(char *param_1,float *param_2,char param_3,char param_4)

{
  undefined4 uVar1;
  code *pcVar2;
  float fVar3;
  float fVar4;
  float fVar5;
  float fVar6;
  float fVar7;
  float fVar8;
  float fVar9;
  float fVar10;
  float fVar11;
  float fVar12;
  float fVar13;
  float fVar14;
  float fVar15;
  float fVar16;
  float fVar17;
  float fVar18;
  float fVar19;
  float fVar20;
  undefined8 uVar21;
  undefined8 uVar22;
  char cVar23;
  ulonglong uVar24;
  char *pcVar25;
  float *pfVar26;
  undefined1 *puVar27;
  undefined1 *puVar28;
  uint uVar29;
  float fVar30;
  undefined1 auStack_78 [8];
  undefined1 auStack_70 [80];
  ulonglong uStack_20;
  
  puVar27 = auStack_78;
  uStack_20 = _DAT_1428792c0 ^ (ulonglong)auStack_78;
  pcVar25 = param_1;
  pfVar26 = param_2;
  puVar28 = auStack_78;
  if ((*param_1 != '\0') &&
     (((param_1[2] != '\0' || (**(longlong **)(param_2 + 0x42) == 0)) ||
      (puVar28 = auStack_78, **(longlong **)(**(longlong **)(param_2 + 0x42) + 0x520) == 0)))) {
    fVar30 = param_2[1];
    fVar3 = param_2[2];
    fVar4 = param_2[3];
    param_2[0] = 0.0;
    param_2[1] = 0.0;
    param_2[2] = 0.0;
    param_2[3] = 0.0;
    fVar5 = param_2[4];
    fVar6 = param_2[5];
    fVar7 = param_2[6];
    fVar8 = param_2[7];
    param_2[4] = 0.0;
    param_2[5] = 0.0;
    param_2[6] = 0.0;
    param_2[7] = 0.0;
    fVar9 = param_2[8];
    fVar10 = param_2[9];
    fVar11 = param_2[10];
    fVar12 = param_2[0xb];
    param_2[8] = 0.0;
    param_2[9] = 0.0;
    param_2[10] = 0.0;
    param_2[0xb] = 0.0;
    fVar13 = param_2[0xc];
    fVar14 = param_2[0xd];
    fVar15 = param_2[0xe];
    fVar16 = param_2[0xf];
    param_2[0xc] = 0.0;
    param_2[0xd] = 0.0;
    param_2[0xe] = 0.0;
    param_2[0xf] = 0.0;
    fVar17 = param_2[0x10];
    fVar18 = param_2[0x11];
    fVar19 = param_2[0x12];
    fVar20 = param_2[0x13];
    param_2[0x10] = 0.0;
    param_2[0x11] = 0.0;
    param_2[0x12] = 0.0;
    param_2[0x13] = 0.0;
    uVar24 = (ulonglong)(byte)param_1[1];
    fVar30 = fVar3 + fVar19 + fVar15 + fVar7 + fVar11 + *param_2 + fVar17 + fVar13 + fVar5 + fVar9 +
             fVar4 + fVar20 + fVar16 + fVar8 + fVar12 + fVar30 + fVar18 + fVar14 + fVar6 + fVar10;
    if (0x13 < (byte)param_1[1]) {
      pcVar2 = (code *)swi(0x2c);
      uVar24 = (*pcVar2)();
      puVar27 = auStack_70;
    }
    pfVar26[uVar24] = fVar30;
    puVar28 = puVar27;
  }
  fVar30 = *(float *)(pcVar25 + 0x10) + *pfVar26;
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  *pfVar26 = fVar30;
  *pfVar26 = fVar30 * *(float *)(pcVar25 + 0x78);
  fVar30 = *(float *)(pcVar25 + 0x14) + pfVar26[1];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[1] = fVar30;
  pfVar26[1] = fVar30 * *(float *)(pcVar25 + 0x7c);
  fVar30 = *(float *)(pcVar25 + 0x18) + pfVar26[2];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[2] = fVar30;
  pfVar26[2] = fVar30 * *(float *)(pcVar25 + 0x80);
  fVar30 = *(float *)(pcVar25 + 0x1c) + pfVar26[3];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[3] = fVar30;
  pfVar26[3] = fVar30 * *(float *)(pcVar25 + 0x84);
  fVar30 = *(float *)(pcVar25 + 0x20) + pfVar26[4];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[4] = fVar30;
  pfVar26[4] = fVar30 * *(float *)(pcVar25 + 0x88);
  fVar30 = *(float *)(pcVar25 + 0x24) + pfVar26[5];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[5] = fVar30;
  pfVar26[5] = fVar30 * *(float *)(pcVar25 + 0x8c);
  fVar30 = *(float *)(pcVar25 + 0x28) + pfVar26[6];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[6] = fVar30;
  pfVar26[6] = fVar30 * *(float *)(pcVar25 + 0x90);
  fVar30 = *(float *)(pcVar25 + 0x2c) + pfVar26[7];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[7] = fVar30;
  pfVar26[7] = fVar30 * *(float *)(pcVar25 + 0x94);
  fVar30 = *(float *)(pcVar25 + 0x30) + pfVar26[8];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[8] = fVar30;
  pfVar26[8] = fVar30 * *(float *)(pcVar25 + 0x98);
  fVar30 = *(float *)(pcVar25 + 0x34) + pfVar26[9];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[9] = fVar30;
  pfVar26[9] = fVar30 * *(float *)(pcVar25 + 0x9c);
  fVar30 = *(float *)(pcVar25 + 0x38) + pfVar26[10];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[10] = fVar30;
  pfVar26[10] = fVar30 * *(float *)(pcVar25 + 0xa0);
  fVar30 = *(float *)(pcVar25 + 0x3c) + pfVar26[0xb];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0xb] = fVar30;
  pfVar26[0xb] = fVar30 * *(float *)(pcVar25 + 0xa4);
  fVar30 = *(float *)(pcVar25 + 0x40) + pfVar26[0xc];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0xc] = fVar30;
  pfVar26[0xc] = fVar30 * *(float *)(pcVar25 + 0xa8);
  fVar30 = *(float *)(pcVar25 + 0x44) + pfVar26[0xd];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0xd] = fVar30;
  pfVar26[0xd] = fVar30 * *(float *)(pcVar25 + 0xac);
  fVar30 = *(float *)(pcVar25 + 0x48) + pfVar26[0xe];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0xe] = fVar30;
  pfVar26[0xe] = fVar30 * *(float *)(pcVar25 + 0xb0);
  fVar30 = *(float *)(pcVar25 + 0x4c) + pfVar26[0xf];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0xf] = fVar30;
  pfVar26[0xf] = fVar30 * *(float *)(pcVar25 + 0xb4);
  fVar30 = *(float *)(pcVar25 + 0x50) + pfVar26[0x10];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0x10] = fVar30;
  pfVar26[0x10] = fVar30 * *(float *)(pcVar25 + 0xb8);
  fVar30 = *(float *)(pcVar25 + 0x54) + pfVar26[0x11];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0x11] = fVar30;
  pfVar26[0x11] = fVar30 * *(float *)(pcVar25 + 0xbc);
  fVar30 = *(float *)(pcVar25 + 0x58) + pfVar26[0x12];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0x12] = fVar30;
  pfVar26[0x12] = fVar30 * *(float *)(pcVar25 + 0xc0);
  fVar30 = *(float *)(pcVar25 + 0x5c) + pfVar26[0x13];
  if (fVar30 <= 0.0) {
    fVar30 = 0.0;
  }
  pfVar26[0x13] = fVar30;
  pfVar26[0x13] = fVar30 * *(float *)(pcVar25 + 0xc4);
  uVar1 = *(undefined4 *)(pcVar25 + 4);
  *(undefined8 *)(puVar28 + -8) = 0x140a3e9f8;
  func_0x000140893580(param_2 + 0x18,2,uVar1);
  uVar1 = *(undefined4 *)(param_1 + (ulonglong)*(byte *)((longlong)param_2 + 0x1bf) * 4 + 0xe0);
  *(undefined8 *)(puVar28 + -8) = 0x140a3ea13;
  func_0x000140893580(param_2 + 0x18,2,uVar1);
  if (param_4 != '\0') {
    *(undefined8 *)(puVar28 + -8) = 0x140a3ea21;
    cVar23 = func_0x000140c5db60();
    if (cVar23 == '\0') {
      *(undefined8 *)(puVar28 + -8) = 0x140a3ea32;
      uVar29 = func_0x000140b6f850(param_2 + 0x18);
      *(undefined8 *)(puVar28 + 0x40) = 0;
      *(undefined8 *)(puVar28 + 0x48) = 0;
      *(undefined4 *)(puVar28 + 0x4c) = 0x7f7fffff;
      *(undefined4 *)(puVar28 + 0x48) = 0x800000;
      uVar21 = *(undefined8 *)(puVar28 + 0x40);
      uVar22 = *(undefined8 *)(puVar28 + 0x48);
      param_2[0x1b] =
           (float)(uVar29 ^ (uint)((longlong)(puVar28 + 0x2c) >> 3) ^ 0x8637d1b6 ^
                   (uint)((longlong)(puVar28 + 0x2c) >> 3) ^ 0x8637d1b6);
      uVar29 = (uint)((longlong)(param_2 + 0x1b) >> 3) ^ (uint)param_2[0x1b] ^ 0x8637d1b6;
      fVar30 = (float)(uVar29 >> 0x11 | uVar29 << 0xf);
      param_2[0x1b] = fVar30;
      param_2[0x1a] = (float)((uint)fVar30 ^ 0x2c67b217);
      *(undefined8 *)(puVar28 + 0x30) = 0;
      *(undefined8 *)(puVar28 + 0x38) = 0;
      *(undefined4 *)(puVar28 + 0x38) = 0x3f800000;
      fVar30 = *(float *)(puVar28 + 0x30);
      fVar3 = *(float *)(puVar28 + 0x34);
      fVar4 = *(float *)(puVar28 + 0x38);
      fVar5 = *(float *)(puVar28 + 0x3c);
      *(undefined1 *)(param_2 + 0x24) = 0;
      param_2[0x1c] = fVar30;
      param_2[0x1d] = fVar3;
      param_2[0x1e] = fVar4;
      param_2[0x1f] = fVar5;
      *(undefined8 *)(param_2 + 0x20) = uVar21;
      *(undefined8 *)(param_2 + 0x22) = uVar22;
    }
  }
  uVar1 = *(undefined4 *)(param_1 + 8);
  *(undefined8 *)(puVar28 + -8) = 0x140a3eac8;
  func_0x000140893580(param_2 + 0x26,0,uVar1);
  if (param_3 != '\0') {
    uVar1 = *(undefined4 *)(param_1 + 0xc);
    *(undefined1 **)(puVar28 + -8) = &LAB_140a3eae0;
    func_0x000140893580(param_2 + 0x34,2,uVar1);
  }
  param_2[0x8f] = *(float *)(param_1 + 0x104) * param_2[0x8f];
  param_2[0x8e] = (float)((uint)param_2[0x8e] | *(uint *)(param_1 + 0x110));
  uVar24 = 0;
  do {
    uVar29 = 1 << ((byte)uVar24 & 0x1f);
    if ((*(uint *)(param_1 + 0x108) & uVar29) == 0) {
      *(undefined1 *)((uVar24 & 0xff) + 0x218 + (longlong)param_2) = 0;
    }
    if ((*(uint *)(param_1 + 0x10c) & uVar29) != 0) {
      *(undefined1 **)(puVar28 + -8) = &LAB_140a3eb46;
      func_0x0001404b79f0(param_2,uVar24 & 0xff,1);
    }
    uVar24 = uVar24 + 1;
  } while (uVar24 < 0x1e);
  if (*(float *)(param_1 + 0x100) != _DAT_14288d5e8) {
    param_2[0x99] = *(float *)(param_1 + 0x100);
  }
  *(undefined8 *)(puVar28 + -8) = 0x140a3eb70;
  FUN_141bf6fc0(*(ulonglong *)(puVar28 + 0x58) ^ (ulonglong)puVar28);
  return;
}

